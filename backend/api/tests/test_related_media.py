"""Related cases and their combined history, through the API. No model or network is used."""

import io

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.api.app import main
from backend.api.app.main import MEDIA_UPLOAD_PATH, app
from backend.api.tests.test_accounts import signed_in
from backend.media import analyze_media
from backend.media.tests.helpers import FakeClassifier, patterned_image

client = TestClient(app)


@pytest.fixture(autouse=True)
def fake_detector_and_empty_store(monkeypatch):
    main.CASES.clear()
    main.CASE_STORE.clear()
    monkeypatch.setattr(main, "analyze_media", lambda path, **kwargs: analyze_media(path, classifier=FakeClassifier(0.1)))
    yield
    main.CASES.clear()
    main.CASE_STORE.clear()


def png(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def picture(seed=1):
    return patterned_image(seed, 512).convert("RGB")


def upload(data, by=client):
    response = by.post(MEDIA_UPLOAD_PATH, files={"file": ("a.png", data, "image/png")})
    assert response.status_code == 200
    return response.json()["case_id"]


def related(case_id, by=client):
    response = by.get(f"/api/cases/{case_id}/related-media")
    assert response.status_code == 200
    return response.json()


def test_a_cropped_repost_finds_the_earlier_case_and_says_why():
    first = upload(png(picture()))
    second = upload(png(picture().crop((12, 12, 500, 500))))
    upload(png(picture(2)))
    body = related(second)
    assert body["status"] == "complete"
    assert body["compared_cases"] == 2
    assert [(item["case_id"], item["kind"], item["through_case_id"]) for item in body["cases"]] == [(first, "likely_same_image", None)]
    assert {"phash", "dhash", "whash"} <= set(body["cases"][0]["distances"])
    assert body["limitations"]


def test_the_same_file_is_an_exact_copy_and_the_score_does_not_move():
    data = png(picture())
    first = upload(data)
    second = upload(data)
    assert related(second)["cases"][0]["kind"] == "exact_copy"
    one, two = client.get(f"/api/cases/{first}").json(), client.get(f"/api/cases/{second}").json()
    assert one["modules"]["media"]["score"] == two["modules"]["media"]["score"]


def test_an_unrelated_picture_finds_nothing():
    upload(png(picture()))
    body = related(upload(png(picture(2))))
    assert body["cases"] == []
    assert body["history"] == []


def test_a_case_without_fingerprints_says_so():
    response = client.post("/api/cases/analyze", json={"text": "A claim about a flood in the city today."})
    body = related(response.json()["case_id"])
    assert body["status"] == "not_applicable"
    assert body["reason"]


def test_an_unknown_case_is_not_found():
    assert client.get("/api/cases/nope/related-media").status_code == 404


def test_other_accounts_cases_are_never_compared_and_signed_out_cases_share_a_pool():
    alice, bob = signed_in(), signed_in()
    alice_case = upload(png(picture()), alice)
    bob_case = upload(png(picture()), bob)
    assert related(bob_case, bob)["cases"] == []
    first = upload(png(picture()))
    second = upload(png(picture()))
    assert [item["case_id"] for item in related(second)["cases"]] == [first]
    assert related(alice_case, alice)["cases"] == []
    # Another account can't ask about the case either.
    assert bob.get(f"/api/cases/{alice_case}/related-media").status_code == 404


def test_the_history_joins_what_each_case_found_and_never_says_source():
    first = upload(png(picture()))
    second = upload(png(picture().crop((12, 12, 500, 500))))
    main.CASE_STORE.save_detail(
        first,
        "network",
        {"coverage": {"spread": [{"posted_at": "2026-01-02T00:00:00Z", "handle": "u1", "platform": "bluesky", "permalink": "https://bsky.app/p/1", "matched_on": "link"}]}},
    )
    main.CASE_STORE.save_detail(
        second,
        "provenance",
        {"appearances": [
            {"observed_at": "2026-01-01T00:00:00Z", "domain": "news.example", "page_url": "https://news.example/a", "match_type": "full"},
            {"observed_at": "2026-01-03T00:00:00Z", "domain": "again.example", "page_url": "https://news.example/a", "match_type": "full"},
            {"observed_at": None, "domain": "undated.example", "page_url": "https://undated.example/a", "match_type": "partial"},
        ]},
    )
    history = related(second)["history"]
    real = [event for event in history if event["kind"] != "submitted"]
    assert [event["url"] for event in real] == ["https://news.example/a", "https://bsky.app/p/1", "https://undated.example/a"]
    assert [event["earliest_found"] for event in real] == [True, False, False]
    assert {event["case_id"] for event in real} == {first, second}
    assert real[-1]["at"] is None
    assert "the source" not in " ".join(event["label"] for event in history)


def test_a_replayed_history_keeps_its_label_and_is_never_the_earliest_found():
    first = upload(png(picture()))
    second = upload(png(picture().crop((12, 12, 500, 500))))
    main.CASE_STORE.save_detail(
        first,
        "network",
        {"coverage": {"synthetic": True, "spread": [{"posted_at": "2020-01-01T00:00:00Z", "handle": "sim", "platform": "bluesky", "permalink": "https://bsky.app/p/9"}]}},
    )
    event = next(item for item in related(second)["history"] if item["kind"] == "public_post")
    assert event["synthetic"] is True
    assert event["url"] is None
    assert event["earliest_found"] is False


def test_a_heavy_crop_links_by_visible_content_only():
    pytest.importorskip("cv2")
    blocks = np.random.default_rng(5).integers(0, 256, (48, 48, 3), dtype=np.uint8)
    detailed = Image.fromarray(blocks).resize((640, 640), Image.Resampling.NEAREST)
    first = upload(png(detailed))
    second = upload(png(detailed.crop((128, 128, 512, 512))))
    cases = related(second)["cases"]
    assert [(item["case_id"], item["kind"]) for item in cases] == [(first, "shares_visible_content")]
    assert cases[0]["agreeing_features"] >= 9
    assert cases[0]["links_from_start"] == 1


def test_saved_features_stay_out_of_every_response():
    case_id = upload(png(picture()))
    assert "local_features" not in client.get(f"/api/cases/{case_id}").text
    assert "local_features" not in client.get(f"/api/cases/{case_id}/related-media").text


def test_a_bad_saved_record_is_skipped():
    case_id = upload(png(picture()))
    other = upload(png(picture(2)))
    main.CASE_STORE.save_detail(other, "media_fingerprints", {"bad": "record"})
    assert related(case_id)["status"] == "complete"
