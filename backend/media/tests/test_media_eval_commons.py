"""The Commons fetcher's rules. A stand-in replaces every network call."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from PIL import Image

from backend.media.eval import fetch_commons
from backend.media.eval.fetch_commons import (
    Plan,
    _plain,
    _title_batches,
    describe_files,
    fetch_plan,
    licence_allowed,
    list_files,
    main,
    usable,
)
from backend.media.eval.recompress import main as recompress_main
from backend.media.eval.recompress import recompress_tree
from backend.media.tests.helpers import patterned_image

REAL_PLAN = Plan("real", "people", ("People",), "2020-01-01")
FAKE_PLAN = Plan("fake", "ai_generated", ("AI",))
THUMB = "https://upload.wikimedia.org/thumb/a.jpg"


def info(title="File:A.jpg", licence="CC0", mime="image/jpeg", timestamp="2015-01-01T00:00:00Z", thumb=THUMB):
    return {
        "title": title,
        "mime": mime,
        "timestamp": timestamp,
        "thumburl": thumb,
        "descriptionurl": "https://commons.wikimedia.org/wiki/" + title,
        "extmetadata": {"LicenseShortName": {"value": licence}, "Artist": {"value": '<a href="x">Some &amp; One</a>'}},
    }


@pytest.mark.parametrize(
    "name",
    ["CC0", "Public domain", "PD-algorithm", "PD Old", "CC BY 4.0", "CC BY-SA 3.0", "CC-BY-SA-4.0", "cc by 2.0"],
)
def test_open_licences_are_accepted(name):
    assert licence_allowed(name) is True


@pytest.mark.parametrize(
    "name",
    [None, "", "All rights reserved", "CC BY-NC 4.0", "CC BY-ND 4.0", "CC BY-NC-SA 2.0", "Fair use", "GFDL", "Copyrighted", "Unknown"],
)
def test_other_licences_are_refused(name):
    assert licence_allowed(name) is False


def test_usable_checks_licence_type_date_and_host():
    assert usable(info(), REAL_PLAN) is True
    assert usable(info(licence="CC BY-NC 4.0"), REAL_PLAN) is False
    assert usable(info(mime="image/svg+xml"), REAL_PLAN) is False
    assert usable(info(timestamp="2023-05-01T00:00:00Z"), REAL_PLAN) is False
    assert usable(info(thumb="https://evil.test/a.jpg"), REAL_PLAN) is False
    assert usable(info(thumb="http://upload.wikimedia.org/a.jpg"), REAL_PLAN) is False


def test_both_commons_image_hosts_are_accepted_and_lookalikes_are_not():
    assert usable(info(thumb="https://thumb.wikimedia.org/wikipedia/commons/thumb/a.jpg"), REAL_PLAN) is True
    assert usable(info(thumb="https://upload.wikimedia.org/wikipedia/commons/a.jpg"), REAL_PLAN) is True
    assert usable(info(thumb="https://thumb.wikimedia.org.evil.test/a.jpg"), REAL_PLAN) is False
    assert usable(info(thumb="http://thumb.wikimedia.org/a.jpg"), REAL_PLAN) is False


def test_date_limit_applies_only_to_real_photos():
    assert usable(info(timestamp="2023-05-01T00:00:00Z"), FAKE_PLAN) is True


def test_generated_images_filed_under_people_are_left_out():
    assert usable(info(title="File:Stable Diffusion woman.jpg"), REAL_PLAN) is False
    assert usable(info(title="File:AI-generated man.jpg"), REAL_PLAN) is False
    assert usable(info(title="File:Stable Diffusion woman.jpg"), FAKE_PLAN) is True


def test_author_html_is_reduced_to_text():
    assert _plain('<a href="x">Some &amp; One</a> <script>x</script>') == "Some & One x"
    assert _plain(None) == ""


class FakeCommons:
    def __init__(self, members, described):
        self.members = members
        self.described = described
        self.downloads = []

    def __call__(self, url):
        if url.startswith("https://upload.wikimedia.org/"):
            self.downloads.append(url)
            return b"image bytes"
        query = parse_qs(urlsplit(url).query)
        if "cmtitle" in query:
            name = query["cmtitle"][0].removeprefix("Category:")
            return json.dumps({"query": {"categorymembers": self.members.get(name, [])}}).encode()
        titles = query["titles"][0].split("|")
        pages = {
            str(i): {"title": t, "imageinfo": [self.described[t]]} for i, t in enumerate(titles) if t in self.described
        }
        return json.dumps({"query": {"pages": pages}}).encode()


def test_walk_follows_subcategories_within_the_depth_limit():
    members = {
        "Root": [{"title": "File:1.jpg"}, {"title": "Category:Sub"}],
        "Sub": [{"title": "File:2.jpg"}, {"title": "File:1.jpg"}, {"title": "Category:Deep"}],
        "Deep": [{"title": "File:3.jpg"}, {"title": "Category:TooDeep"}],
        "TooDeep": [{"title": "File:4.jpg"}],
    }
    assert list_files(FakeCommons(members, {}), ["Root"], limit=10, max_depth=2) == ["File:1.jpg", "File:2.jpg", "File:3.jpg"]


def test_walk_survives_a_category_loop():
    members = {"A": [{"title": "Category:B"}], "B": [{"title": "Category:A"}, {"title": "File:1.jpg"}]}
    assert list_files(FakeCommons(members, {}), ["A"], limit=10) == ["File:1.jpg"]


def test_fetch_keeps_only_allowed_files_and_records_their_licence(tmp_path):
    names = [f"File:Named Person {n}.jpg" for n in range(4)]
    described = {
        names[0]: info(names[0], licence="CC BY 4.0", thumb="https://upload.wikimedia.org/0.jpg"),
        names[1]: info(names[1], licence="All rights reserved", thumb="https://upload.wikimedia.org/1.jpg"),
        names[2]: info(names[2], licence="CC0", thumb="https://upload.wikimedia.org/2.jpg"),
        names[3]: info(names[3], licence="CC0", thumb="https://upload.wikimedia.org/3.jpg"),
    }
    commons = FakeCommons({"People": [{"title": n} for n in names]}, described)
    kept = fetch_plan(REAL_PLAN, tmp_path, 2, commons, seed=0, delay_s=0)
    assert len(kept) == 2
    assert len(commons.downloads) == 2
    assert "https://upload.wikimedia.org/1.jpg" not in commons.downloads
    for record in kept:
        assert record["licence"] in {"CC BY 4.0", "CC0"}
        assert record["author"] == "Some & One"
        assert record["page"].startswith("https://commons.wikimedia.org/wiki/")
        assert "Named Person" not in record["file"]
        assert (tmp_path / record["file"]).read_bytes() == b"image bytes"


def test_long_titles_are_split_so_the_url_stays_short():
    # Non-ASCII characters grow when encoded, which is how the first real run hit HTTP 414.
    titles = [f"File:{'é' * 200} {n}.jpg" for n in range(50)]
    commons = FakeCommons({}, {title: info(title) for title in titles})
    lengths = []

    def measuring(url):
        lengths.append(len(url))
        return commons(url)

    described = describe_files(measuring, titles)
    assert {item["title"] for item in described} == set(titles)
    assert len(lengths) > 1
    assert max(lengths) < 5000


def test_batches_never_exceed_the_title_limit():
    titles = [f"File:{n}.jpg" for n in range(120)]
    batches = list(_title_batches(titles))
    assert [len(batch) for batch in batches] == [50, 50, 20]
    assert [title for batch in batches for title in batch] == titles


def test_one_very_long_title_is_still_requested():
    title = f"File:{'é' * 2000}.jpg"
    assert list(_title_batches([title])) == [[title]]


def test_manifest_survives_a_failure_in_a_later_category(tmp_path, monkeypatch):
    plans = (Plan("fake", "first", ("One",)), Plan("fake", "second", ("Two",)))
    monkeypatch.setattr(fetch_commons, "PLANS", plans)
    title = "File:A.jpg"
    commons = FakeCommons({"One": [{"title": title}]}, {title: info(title)})

    def failing(url):
        if "Two" in url:
            raise OSError("Commons went away")
        return commons(url)

    with pytest.raises(OSError):
        main(["--out", str(tmp_path), "--delay", "0"], failing)
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert [record["category"] for record in manifest["files"]] == ["first"]
    assert manifest["files"][0]["licence"] == "CC0"


def test_failed_download_is_skipped(tmp_path):
    title = "File:A.jpg"
    commons = FakeCommons({"People": [{"title": title}]}, {title: info(title)})

    attempts = []

    def failing(url):
        if url == THUMB:
            attempts.append(url)
            raise OSError("gone")
        return commons(url)

    assert fetch_plan(REAL_PLAN, tmp_path, 5, failing, seed=0, delay_s=0) == []
    assert attempts == [THUMB]


def test_recompressed_copies_keep_the_layout_and_lose_quality(tmp_path):
    source = tmp_path / "in"
    (source / "fake" / "ai_generated").mkdir(parents=True)
    original = source / "fake" / "ai_generated" / "a.png"
    patterned_image(seed=3, size=1600).save(original)
    (source / "fake" / "ai_generated" / "notes.txt").write_text("skip me", encoding="utf-8")
    (source / "fake" / "ai_generated" / "broken.jpg").write_bytes(b"not an image")
    written, failed = recompress_tree(source, tmp_path / "out")
    assert (written, failed) == (1, 1)
    with Image.open(tmp_path / "out" / "fake" / "ai_generated" / "a.jpg") as copy:
        assert copy.format == "JPEG"
        assert max(copy.size) == 800


def test_recompressed_copies_cannot_be_saved_inside_the_repository(tmp_path, capsys):
    inside = Path(__file__).resolve().parents[3] / "data" / "eval" / "copies"
    assert recompress_main(["--in", str(tmp_path), "--out", str(inside)]) == 2
    assert "outside the repository" in capsys.readouterr().err
    assert not inside.exists()


def test_images_cannot_be_saved_inside_the_repository(capsys):
    inside = Path(__file__).resolve().parents[3] / "data" / "eval" / "images"
    assert main(["--out", str(inside)], fetch=lambda url: pytest.fail("It used the network.")) == 2
    assert "outside the repository" in capsys.readouterr().err
    assert not inside.exists()
