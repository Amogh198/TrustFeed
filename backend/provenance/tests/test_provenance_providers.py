"""Provider parsing against responses shaped like the documented ones. No network."""

from __future__ import annotations

import base64
import io
import json

import pytest
from PIL import Image

from backend.media.tests.helpers import patterned_image
from backend.provenance.config import ProvenanceConfig
from backend.provenance.models import MatchType
from backend.provenance.providers import (
    GoogleVisionWeb,
    ProviderFailure,
    SerpApiLens,
    TinEye,
    Upload,
    configured_providers,
)
from backend.provenance.safe_http import HttpFailed, HttpResponse
from backend.provenance.tests.helpers import FakeHttp

KEY = "test-key-value"
CONFIG = ProvenanceConfig()


def ok(url, payload, status=200) -> HttpResponse:
    return HttpResponse(url=url, status=status, body=json.dumps(payload).encode())


def upload() -> Upload:
    return Upload(patterned_image())


VISION_RESPONSE = {
    "responses": [
        {
            "webDetection": {
                "pagesWithMatchingImages": [
                    {
                        "url": "https://news.test/story",
                        "pageTitle": "A story",
                        "fullMatchingImages": [{"url": "https://news.test/a.jpg"}],
                    },
                    {
                        "url": "https://blog.test/post",
                        "partialMatchingImages": [{"url": "https://blog.test/crop.jpg"}],
                    },
                    {"url": "javascript:alert(1)", "pageTitle": "bad link"},
                ],
                "fullMatchingImages": [{"url": "https://news.test/a.jpg"}, {"url": "https://cdn.test/orphan.jpg"}],
                "visuallySimilarImages": [{"url": "https://other.test/similar.jpg"}],
            }
        }
    ]
}


def test_vision_parses_pages_and_images_and_has_no_dates():
    http = FakeHttp({GoogleVisionWeb.url: ok(GoogleVisionWeb.url, VISION_RESPONSE)})
    found = GoogleVisionWeb(KEY).search(upload(), http, CONFIG)
    by_url = {c.page_url or c.image_url: c for c in found}
    assert by_url["https://news.test/story"].match_type is MatchType.EXACT
    assert by_url["https://news.test/story"].image_url == "https://news.test/a.jpg"
    assert by_url["https://news.test/story"].page_title == "A story"
    assert by_url["https://blog.test/post"].match_type is MatchType.PARTIAL
    assert by_url["https://cdn.test/orphan.jpg"].page_url is None
    assert by_url["https://other.test/similar.jpg"].match_type is MatchType.SIMILAR
    assert "javascript:alert(1)" not in by_url
    assert all(c.crawl_date is None for c in found)


def test_vision_sends_pixels_only_with_the_key_in_a_header():
    http = FakeHttp({GoogleVisionWeb.url: ok(GoogleVisionWeb.url, VISION_RESPONSE)})
    GoogleVisionWeb(KEY).search(upload(), http, CONFIG)
    call = http.calls[0]
    assert call["headers"]["x-goog-api-key"] == KEY
    assert KEY not in call["url"]
    assert KEY.encode() not in call["body"]
    assert call["max_redirects"] == 0  # A redirect must never carry the image or key elsewhere.
    request = json.loads(call["body"])["requests"][0]
    assert request["features"][0]["type"] == "WEB_DETECTION"
    Image.open(io.BytesIO(base64.b64decode(request["image"]["content"]))).verify()


def test_upload_removes_exif_data():
    source = patterned_image()
    exif = Image.Exif()
    exif[0x010F] = "PrivateCameraMaker"
    buffer = io.BytesIO()
    source.save(buffer, format="JPEG", exif=exif)
    buffer.seek(0)
    with Image.open(buffer) as loaded:
        assert loaded.getexif().get(0x010F) == "PrivateCameraMaker"
        sent = Upload(loaded).jpeg(4 * 1024 * 1024)
    assert b"PrivateCameraMaker" not in sent
    assert not Image.open(io.BytesIO(sent)).getexif()


def test_upload_shrinks_to_the_serpapi_limit():
    noisy = Image.effect_noise((3000, 3000), 90).convert("RGB")
    assert len(Upload(noisy).jpeg(500 * 1024)) <= 500 * 1024


def test_upload_reports_an_impossible_limit():
    with pytest.raises(ProviderFailure):
        Upload(Image.effect_noise((3000, 3000), 90).convert("RGB")).jpeg(100)


def test_vision_error_inside_a_200_response_is_a_failure():
    payload = {"responses": [{"error": {"code": 3, "message": "details from the service"}}]}
    http = FakeHttp({GoogleVisionWeb.url: ok(GoogleVisionWeb.url, payload)})
    with pytest.raises(ProviderFailure) as caught:
        GoogleVisionWeb(KEY).search(upload(), http, CONFIG)
    assert "details from the service" not in str(caught.value)


def test_vision_no_results_is_an_empty_list():
    http = FakeHttp({GoogleVisionWeb.url: ok(GoogleVisionWeb.url, {"responses": [{}]})})
    assert GoogleVisionWeb(KEY).search(upload(), http, CONFIG) == []


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (HttpResponse(url="", status=429, body=b"{}"), "rate limited"),
        (HttpResponse(url="", status=403, body=b"{}"), "rejected the API key"),
        (HttpResponse(url="", status=401, body=b"{}"), "rejected the API key"),
        (HttpResponse(url="", status=500, body=b"oops"), "server error"),
        (HttpResponse(url="", status=200, body=b"<html>not json"), "could not be read"),
        (HttpResponse(url="", status=200, body=b"[1, 2]"), "could not be read"),
        (HttpResponse(url="", status=400, body=b"{}"), "refused"),
        (HttpResponse(url="", status=200, body=b'{"responses": []}'), "could not be read"),
        (HttpFailed("timeout"), "timed out"),
        (HttpFailed("network"), "could not be reached"),
    ],
)
def test_vision_failures_have_safe_reasons(response, expected):
    http = FakeHttp({GoogleVisionWeb.url: response})
    with pytest.raises(ProviderFailure) as caught:
        GoogleVisionWeb(KEY).search(upload(), http, CONFIG)
    assert expected in str(caught.value)
    assert KEY not in str(caught.value)


def test_malformed_field_types_are_ignored():
    payload = {
        "responses": [
            {
                "webDetection": {
                    "pagesWithMatchingImages": ["text", {"url": 5}, {"url": "https://ok.test/p", "pageTitle": 7}],
                    "fullMatchingImages": "not a list",
                    "visuallySimilarImages": [None],
                }
            }
        ]
    }
    http = FakeHttp({GoogleVisionWeb.url: ok(GoogleVisionWeb.url, payload)})
    found = GoogleVisionWeb(KEY).search(upload(), http, CONFIG)
    assert [c.page_url for c in found] == ["https://ok.test/p"]
    assert found[0].page_title is None


TINEYE_RESPONSE = {
    "code": 200,
    "messages": [],
    "stats": {"total_results": 1},
    "results": {
        "matches": [
            {
                "image_url": "https://cdn.tineye.test/x.jpg",
                "domain": "site.test",
                "score": 95,
                "backlinks": [
                    {"url": "https://site.test/a.jpg", "backlink": "https://site.test/page", "crawl_date": "2014-03-09"},
                    {"url": "https://two.test/a.jpg", "backlink": "https://two.test/page", "crawl_date": "garbage"},
                    {"url": "ftp://bad.test/a.jpg", "backlink": "ftp://bad.test/page"},
                ],
            }
        ]
    },
}


def test_tineye_reads_backlinks_and_crawl_dates():
    http = FakeHttp({TinEye.url: ok(TinEye.url, TINEYE_RESPONSE)})
    found = TinEye(KEY).search(upload(), http, CONFIG)
    assert [c.page_url for c in found[:2]] == ["https://site.test/page", "https://two.test/page"]
    assert found[0].crawl_date.isoformat() == "2014-03-09T00:00:00+00:00"
    assert found[1].crawl_date is None
    assert all(c.decide_type_by_phash for c in found)
    assert len(found) == 3  # The ftp backlink falls back to the match's own image URL.
    assert found[2].page_url is None


def test_tineye_asks_for_oldest_first_with_the_key_in_a_header():
    http = FakeHttp({TinEye.url: ok(TinEye.url, TINEYE_RESPONSE)})
    TinEye(KEY).search(upload(), http, CONFIG)
    call = http.calls[0]
    assert call["headers"]["x-api-key"] == KEY
    assert b'name="sort"\r\n\r\ncrawl_date' in call["body"]
    assert b'name="order"\r\n\r\nasc' in call["body"]
    assert b'name="image_upload"; filename="image.jpg"' in call["body"]
    assert KEY.encode() not in call["body"]


def test_tineye_error_code_is_a_failure():
    http = FakeHttp({TinEye.url: ok(TinEye.url, {"code": 400, "messages": ["Image too simple"]})})
    with pytest.raises(ProviderFailure):
        TinEye(KEY).search(upload(), http, CONFIG)


def serp_http(search_payload, upload_payload=None):
    routes = {SerpApiLens.upload_url: ok(SerpApiLens.upload_url, upload_payload or {"image_id": "img123"})}

    class Router(FakeHttp):
        def __call__(self, url, **options):
            if url.startswith(SerpApiLens.search_url + "?"):
                self.calls.append({"url": url, **options})
                return ok(url, search_payload)
            return super().__call__(url, **options)

    return Router(routes)


def test_serpapi_uploads_then_searches_exact_matches():
    payload = {
        "exact_matches": [
            {
                "position": 1,
                "title": "A page",
                "link": "https://news.test/x",
                "thumbnail": "https://serpapi.test/t.jpg",
                "date": "2 years ago",
            },
            {"position": 2, "title": "No link"},
        ]
    }
    http = serp_http(payload)
    found = SerpApiLens(KEY).search(upload(), http, CONFIG)
    assert len(found) == 1
    assert found[0].match_type is MatchType.EXACT
    assert found[0].provider_date_text == "2 years ago"
    assert found[0].crawl_date is None
    assert "image_id=img123" in http.calls[1]["url"]
    assert "type=exact_matches" in http.calls[1]["url"]
    assert len(http.calls[0]["body"]) <= 600 * 1024


def test_serpapi_no_results_message_is_an_empty_list():
    http = serp_http({"error": "Google Lens hasn't returned any results for this query."})
    assert SerpApiLens(KEY).search(upload(), http, CONFIG) == []


def test_serpapi_other_errors_are_failures_without_their_text():
    http = serp_http({"error": "Your account has run out of searches."})
    with pytest.raises(ProviderFailure) as caught:
        SerpApiLens(KEY).search(upload(), http, CONFIG)
    assert "run out" not in str(caught.value)


def test_serpapi_refused_upload_is_a_failure():
    http = serp_http({}, upload_payload={"error": "invalid format"})
    with pytest.raises(ProviderFailure):
        SerpApiLens(KEY).search(upload(), http, CONFIG)


def test_only_providers_with_keys_are_configured():
    assert configured_providers(ProvenanceConfig()) == []
    names = [p.name for p in configured_providers(ProvenanceConfig(vision_api_key="a", serpapi_api_key="b"))]
    assert names == ["google_vision_web", "serpapi_google_lens"]


def test_keys_are_not_in_the_config_repr():
    config = ProvenanceConfig(vision_api_key=KEY, tineye_api_key=KEY, serpapi_api_key=KEY)
    assert KEY not in repr(config)


def test_config_reads_keys_from_the_environment(monkeypatch):
    monkeypatch.setenv("GOOGLE_VISION_API_KEY", "abc")
    monkeypatch.setenv("TINEYE_API_KEY", "  ")
    config = ProvenanceConfig.from_env()
    assert config.vision_api_key == "abc"
    assert config.tineye_api_key is None
