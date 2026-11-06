"""Reading pictures on found posts, and treating altered copies as one image. No network is used."""

import time
from urllib.parse import quote

import numpy as np
import pytest
from PIL import Image

from backend.media.fingerprint import compute_fingerprints
from backend.network import trace_public_spread
from backend.network.dataset import Post
from backend.network.post_images import (
    FEATURES_KEY,
    MAX_IMAGES,
    MAX_IMAGES_PER_POST,
    compare_post_images,
    read_post_image,
)
from backend.network.significance import link_fingerprints
from backend.network.sources import BlueskySource, LemmySource, MastodonSource, PublicPost
from backend.network.sources.base import text_links

ITEM = "https://story.example/flood"
START = "2026-03-01T09:00:00Z"


def picture(seed=1, size=512):
    coarse = np.random.default_rng(seed).integers(0, 256, (8, 8, 3), dtype=np.uint8)
    return Image.fromarray(coarse).resize((size, size), Image.Resampling.BICUBIC)


def cropped(seed=1, by=12, size=512):
    return picture(seed, size).crop((by, by, size - by, size - by))


def public_post(number, *links, text="A shared story"):
    return PublicPost(
        id=f"p{number}",
        platform="bluesky",
        author_id=f"a{number}",
        author_handle=f"u{number}",
        author_ref=f"a{number}",
        text=text,
        created_at=f"2026-03-01T09:00:{number:02d}Z",
        permalink=f"https://bsky.app/profile/u{number}/post/{number}",
        image_urls=links,
    )


def test_text_links_drops_values_that_are_not_text():
    assert text_links("https://a.example/1.png", None, 7, ["x"], "https://a.example/1.png") == ("https://a.example/1.png",)


def test_mastodon_reads_previews_and_keeps_posts_with_bad_fields():
    post = MastodonSource()._parse(
        {
            "visibility": "public",
            "uri": "https://m.example/1",
            "url": "https://m.example/@u/1",
            "created_at": START,
            "content": "<p>hello</p>",
            "account": {"id": "9", "acct": "u"},
            "media_attachments": [{"preview_url": "https://m.example/1.png"}, {"preview_url": 7}, "bad"],
        }
    )
    assert post.image_urls == ("https://m.example/1.png",)


@pytest.mark.parametrize(
    ("embed", "expected"),
    [
        ({"images": [{"thumb": "https://b.example/1.jpg"}, {"thumb": None}, "bad"]}, ("https://b.example/1.jpg",)),
        ({"thumbnail": "https://b.example/video.jpg"}, ("https://b.example/video.jpg",)),
        ({"external": {"thumb": "https://b.example/card.jpg"}}, ("https://b.example/card.jpg",)),
        ({"media": {"images": [{"thumb": "https://b.example/quote.jpg"}]}}, ("https://b.example/quote.jpg",)),
        ("bad", ()),
        (None, ()),
    ],
)
def test_bluesky_finds_thumbnails_in_each_embed_kind(embed, expected):
    from backend.network.sources.bluesky import _picture_links

    assert _picture_links({"embed": embed}) == expected


def test_lemmy_reads_thumbnails_and_picture_links_only():
    from backend.network.sources.lemmy import _picture_link

    assert _picture_link("https://l.example/a.PNG?x=1") == "https://l.example/a.PNG?x=1"
    assert _picture_link("https://l.example/page") is None
    assert _picture_link(7) is None
    assert LemmySource is not None


def test_a_changed_copy_is_noted_and_a_different_picture_is_not():
    links = {"https://x.example/copy.png": cropped(1), "https://x.example/other.png": picture(2)}
    readout = compare_post_images(
        [public_post(1, "https://x.example/copy.png"), public_post(2, "https://x.example/other.png")],
        {},
        [compute_fingerprints(picture(1))],
        lambda url: compute_fingerprints(links[url]),
    )
    assert readout.same_as_submitted == {"p1"}
    assert readout.read == 2
    assert set(readout.by_post) == {"p1", "p2"}


def test_a_picture_that_fails_is_counted_and_keeps_the_rest():
    def reader(url):
        if "bad" in url:
            raise OSError("broken")
        return None if "none" in url else compute_fingerprints(picture(1))

    readout = compare_post_images(
        [public_post(1, "https://x.example/bad.png"), public_post(2, "https://x.example/none.png"), public_post(3, "https://x.example/ok.png")],
        {},
        [],
        reader,
    )
    assert (readout.read, readout.failed) == (1, 2)


def test_only_public_web_links_are_read():
    seen = []
    compare_post_images(
        [public_post(1, "file:///etc/passwd", "javascript:alert(1)", "https://x.example/ok.png")],
        {},
        [],
        lambda url: seen.append(url) or None,
    )
    assert seen == ["https://x.example/ok.png"]


def test_limits_are_kept_and_reported():
    many = [public_post(number, f"https://x.example/{number}.png") for number in range(MAX_IMAGES + 5)]
    readout = compare_post_images(many, {}, [], lambda url: None)
    assert readout.skipped == 5
    assert readout.failed == MAX_IMAGES
    links = [f"https://x.example/{number}.png" for number in range(MAX_IMAGES_PER_POST + 3)]
    seen = []
    compare_post_images([public_post(1, *links)], {}, [], lambda url: seen.append(url) or None)
    assert len(seen) == MAX_IMAGES_PER_POST


def test_pictures_still_being_read_at_the_deadline_count_as_skipped():
    def slow(url):
        time.sleep(0.5)

    readout = compare_post_images([public_post(1, "https://x.example/a.png")], {}, [], slow, time_budget_s=0.01)
    assert (readout.read, readout.skipped) == (0, 1)


def test_local_features_catch_a_heavy_crop_and_stay_out_of_saved_hashes():
    pytest.importorskip("cv2")
    from backend.media.local_features import compute_features

    def detailed():
        blocks = np.random.default_rng(5).integers(0, 256, (48, 48, 3), dtype=np.uint8)
        return Image.fromarray(blocks).resize((640, 640), Image.Resampling.NEAREST)

    crop = detailed().crop((128, 128, 512, 512))
    readout = compare_post_images(
        [public_post(1, "https://x.example/crop.png")],
        {},
        [compute_fingerprints(detailed())],
        lambda url: {**compute_fingerprints(crop), FEATURES_KEY: compute_features(crop)},
        submitted_features=[compute_features(detailed())],
    )
    assert readout.same_as_submitted == {"p1"}
    assert FEATURES_KEY not in readout.by_post["p1"]


def test_the_picture_reader_returns_nothing_for_a_blocked_or_broken_address(monkeypatch):
    from backend.provenance import safe_http

    class Response:
        status = 200
        body = b"this is not a picture"

    monkeypatch.setattr(safe_http, "safe_request", lambda *args, **kwargs: Response())
    assert read_post_image("https://x.example/a.png") is None

    def blocked(*args, **kwargs):
        raise safe_http.HttpBlocked("private address")

    monkeypatch.setattr(safe_http, "safe_request", blocked)
    assert read_post_image("http://127.0.0.1/a.png") is None


def _post_with(number, image):
    hashes = compute_fingerprints(image)
    from datetime import UTC, datetime, timedelta

    return Post(
        id=f"p{number}",
        account_id=f"a{number}",
        created_at=datetime(2026, 3, 1, tzinfo=UTC) + timedelta(seconds=number),
        media_fingerprint=hashes["phash"],
        media_fingerprint_set=tuple(sorted(hashes.items())),
    )


def test_the_coordination_test_treats_a_cropped_copy_as_one_image():
    posts = [_post_with(1, picture(1)), _post_with(2, cropped(1)), _post_with(3, picture(2))]
    updated, groups = link_fingerprints(posts, 5)
    media = {post.id: post.media_hash for post in updated}
    assert media["p1"] == media["p2"]
    assert media["p3"] != media["p1"]
    assert len(groups) == 1


def test_a_lone_fingerprint_still_uses_the_distance():
    from datetime import UTC, datetime

    moment = datetime(2026, 3, 1, tzinfo=UTC)
    posts = [
        Post(id="p1", account_id="a", created_at=moment, media_fingerprint="ffffffffffffffff"),
        Post(id="p2", account_id="b", created_at=moment, media_fingerprint="fffffffffffffff0"),
    ]
    assert len(link_fingerprints(posts, 5)[1]) == 1


class Fake:
    def __init__(self, responses):
        self.responses = responses

    def __call__(self, url):
        from backend.network.sources import FetchError

        if url in self.responses:
            return self.responses[url]
        raise FetchError("The platform refused the request (HTTP 403)", 403)


def _view(number, thumb):
    return {
        "uri": f"at://did:plc:u{number}/app.bsky.feed.post/{number}",
        "indexedAt": f"2026-03-01T09:00:{number:02d}.000Z",
        "author": {"did": f"did:plc:u{number}", "handle": f"u{number}.example"},
        "record": {"text": "A story", "createdAt": START, "embed": {"external": {"uri": ITEM}}},
        "embed": {"images": [{"thumb": thumb}]},
    }


SEARCH = f"https://api.bsky.app/xrpc/app.bsky.feed.searchPosts?q=*&url={quote(ITEM, safe='')}&sort=latest&limit=100"


def _traced(reader, submitted=()):
    fetch = Fake({SEARCH: {"posts": [_view(1, "https://t.example/copy.jpg"), _view(2, "https://t.example/other.jpg")]}})
    return trace_public_spread("case-i", url=ITEM, fetch=fetch, sources=[BlueskySource()], submitted_hashes=submitted, image_reader=reader)


def test_a_trace_reports_what_it_compared_and_marks_the_matching_post():
    links = {"https://t.example/copy.jpg": cropped(1), "https://t.example/other.jpg": picture(2)}
    result = _traced(lambda url: compute_fingerprints(links[url]), [compute_fingerprints(picture(1))])
    assert result.coverage["images"] == {"status": "complete", "read": 2, "failed": 0, "skipped": 0, "same_as_submitted": 1}
    by_handle = {post["handle"]: post for post in result.coverage["spread"]}
    assert by_handle["u1.example"]["same_picture"] is True
    assert by_handle["u2.example"]["same_picture"] is False
    # A shared link says more about why a post is listed, so it stays the reason.
    assert by_handle["u1.example"]["matched_on"] == "link"
    assert any("can't be searched by image" in line for line in result.module_result["limitations"])
    assert any("look like the submitted file" in line for line in result.module_result["evidence"])


def test_a_trace_without_a_reader_says_pictures_were_not_compared():
    result = _traced(None)
    assert result.coverage["images"]["status"] == "not_run"
    assert all(post["same_picture"] is False for post in result.coverage["spread"])


def test_every_picture_failing_is_reported_and_keeps_the_trace():
    result = _traced(lambda url: None, [compute_fingerprints(picture(1))])
    assert result.coverage["images"]["failed"] == 2
    assert result.coverage["images"]["same_as_submitted"] == 0
    assert len(result.coverage["spread"]) == 2


def test_replays_never_read_pictures(monkeypatch):
    from backend.network import service

    def forbidden(url):
        raise AssertionError("A replay must stay offline.")

    monkeypatch.setattr(service, "read_post_image", forbidden)
    result = service.trace_case("case-r", url=ITEM, fetch=Fake({SEARCH: {"posts": [_view(1, "https://t.example/a.jpg")]}}))
    assert result["status"] == "complete"
