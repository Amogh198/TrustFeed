"""Shared test helpers, in a uniquely named module so other lanes' conftest files cannot shadow them."""

from __future__ import annotations

import io
import json

from backend.media.tests.helpers import patterned_image
from backend.provenance.models import MatchType
from backend.provenance.providers import Candidate
from backend.provenance.safe_http import HttpFailed, HttpResponse


def jpeg_bytes(seed: int = 1, size: int = 256) -> bytes:
    buffer = io.BytesIO()
    patterned_image(seed=seed, size=size).save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def html_page(*, date_ld: str | None = None, og: str | None = None, title: str = "A page") -> bytes:
    parts = [f"<html><head><title>{title}</title>"]
    if date_ld:
        block = {"@context": "https://schema.org", "@type": "Article", "datePublished": date_ld}
        parts.append(f'<script type="application/ld+json">{json.dumps(block)}</script>')
    if og:
        parts.append(f'<meta property="article:published_time" content="{og}">')
    parts.append("</head><body>text</body></html>")
    return "".join(parts).encode()


class FakeHttp:
    """Stands in for safe_request. Unlisted URLs fail, and every call is recorded."""

    def __init__(self, routes: dict | None = None) -> None:
        self.routes = routes or {}
        self.calls: list[dict] = []

    def __call__(self, url, **options):
        self.calls.append({"url": url, **options})
        route = self.routes.get(url)
        if route is None:
            if url.endswith("/robots.txt"):
                return HttpResponse(url=url, status=404)
            raise HttpFailed("network")
        if isinstance(route, Exception):
            raise route
        return route

    def urls(self) -> list[str]:
        return [call["url"] for call in self.calls]


def page_response(url: str, body: bytes, **headers) -> HttpResponse:
    merged = {"content-type": "text/html; charset=utf-8", **{k.replace("_", "-"): v for k, v in headers.items()}}
    return HttpResponse(url=url, status=200, headers=merged, body=body)


def image_response(url: str, body: bytes) -> HttpResponse:
    return HttpResponse(url=url, status=200, headers={"content-type": "image/jpeg"}, body=body)


class FakeProvider:
    def __init__(self, candidates=None, *, error: Exception | None = None, name: str = "fake_provider") -> None:
        self.name = name
        self.candidates = candidates or []
        self.error = error
        self.calls = 0

    def search(self, upload, http, config):
        self.calls += 1
        if self.error:
            raise self.error
        return self.candidates


def candidate(page: str | None = "https://site.test/page", image: str | None = None, **fields) -> Candidate:
    fields.setdefault("match_type", MatchType.EXACT)
    fields.setdefault("provider", "fake_provider")
    return Candidate(page_url=page, image_url=image, **fields)
