"""Reverse image search providers. Each runs only when its key is set.

Only re-encoded pixels are sent, so EXIF data such as GPS never leaves the server.
Provider error text is not passed on: it is replaced with fixed, safe reasons.
"""

from __future__ import annotations

import base64
import io
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import urlencode
from uuid import uuid4

from backend.provenance.classify import clean_text, clean_url
from backend.provenance.config import ProvenanceConfig
from backend.provenance.models import MatchType
from backend.provenance.safe_http import HttpBlocked, HttpFailed, RequestFunction

_MB = 1024 * 1024
_API_RESPONSE_LIMIT = 8 * _MB
_SERPAPI_UPLOAD_LIMIT = 500 * 1024  # Documented by SerpApi's Image API.
_DEFAULT_UPLOAD_LIMIT = 4 * _MB
_NO_RESULTS_MARKER = "hasn't returned any results"


class ProviderFailure(Exception):
    """A provider could not answer. The message is written here and safe to show."""


@dataclass
class Candidate:
    provider: str
    match_type: MatchType
    page_url: str | None = None
    page_title: str | None = None
    image_url: str | None = None
    crawl_date: datetime | None = None
    # Vague date text from a provider, such as "2 years ago". Never used as a date.
    provider_date_text: str | None = None
    # TinEye gives a score rather than a match type, so pHash decides.
    decide_type_by_phash: bool = False


class Upload:
    """Re-encodes the image on demand and remembers each size."""

    def __init__(self, image) -> None:
        self._image = image
        self._cache: dict[int, bytes] = {}

    def jpeg(self, max_bytes: int) -> bytes:
        if max_bytes not in self._cache:
            self._cache[max_bytes] = _encode_within(self._image, max_bytes)
        return self._cache[max_bytes]


def _encode_within(image, max_bytes: int) -> bytes:
    from PIL import Image

    working = image.convert("RGB")
    for side, quality in ((2048, 90), (2048, 75), (1280, 80), (1024, 70), (800, 65), (640, 60), (480, 55)):
        candidate = working.copy()
        candidate.thumbnail((side, side), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        candidate.save(buffer, format="JPEG", quality=quality)
        if buffer.tell() <= max_bytes:
            return buffer.getvalue()
    raise ProviderFailure("The image could not be reduced to the provider's upload limit.")


def _multipart(fields: Mapping[str, str], file_field: str, data: bytes) -> tuple[bytes, str]:
    boundary = f"trustfeed{uuid4().hex}"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="image.jpg"\r\n'
        "Content-Type: image/jpeg\r\n\r\n".encode()
    )
    parts.append(data + f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _call_json(
    name: str,
    http: RequestFunction,
    url: str,
    config: ProvenanceConfig,
    *,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
) -> dict[str, Any]:
    try:
        response = http(
            url,
            method=method,
            headers={"User-Agent": config.user_agent, **(headers or {})},
            body=body,
            timeout_s=config.provider_timeout_s,
            max_bytes=_API_RESPONSE_LIMIT,
            deadline=time.monotonic() + config.provider_timeout_s,
            max_redirects=0,
        )
    except HttpFailed as exc:
        reason = "timed out" if exc.kind == "timeout" else "could not be reached"
        raise ProviderFailure(f"{name} {reason}.") from None
    except HttpBlocked:
        raise ProviderFailure(f"{name} could not be reached.") from None

    if response.status in {401, 403}:
        raise ProviderFailure(f"{name} rejected the API key or the account lacks access.")
    if response.status == 429:
        raise ProviderFailure(f"{name} is rate limited or out of quota.")
    if response.status >= 500:
        raise ProviderFailure(f"{name} had a server error ({response.status}).")
    try:
        payload = json.loads(response.body)
    except (ValueError, RecursionError):
        raise ProviderFailure(f"{name} returned a response that could not be read.") from None
    if not isinstance(payload, dict):
        raise ProviderFailure(f"{name} returned a response that could not be read.")
    if response.status >= 400:
        raise ProviderFailure(f"{name} refused the request ({response.status}).")
    return payload


def _dict_items(value: object) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


class Provider(Protocol):
    name: str

    def search(self, upload: Upload, http: RequestFunction, config: ProvenanceConfig) -> list[Candidate]: ...


class GoogleVisionWeb:
    """Vision Web Detection. Finds pages and image URLs. It reports no dates."""

    name = "google_vision_web"
    url = "https://vision.googleapis.com/v1/images:annotate"

    def __init__(self, api_key: str) -> None:
        self._key = api_key

    def search(self, upload: Upload, http: RequestFunction, config: ProvenanceConfig) -> list[Candidate]:
        request = {
            "requests": [
                {
                    "image": {"content": base64.b64encode(upload.jpeg(_DEFAULT_UPLOAD_LIMIT)).decode("ascii")},
                    "features": [{"type": "WEB_DETECTION", "maxResults": config.max_results_per_provider}],
                }
            ]
        }
        # The key goes in a header, so it cannot end up in any logged URL.
        payload = _call_json(
            self.name,
            http,
            self.url,
            config,
            method="POST",
            headers={"Content-Type": "application/json", "x-goog-api-key": self._key},
            body=json.dumps(request).encode(),
        )
        responses = _dict_items(payload.get("responses"))
        if not responses:
            raise ProviderFailure(f"{self.name} returned a response that could not be read.")
        if responses[0].get("error"):
            raise ProviderFailure(f"{self.name} could not process this image.")
        return self._parse(responses[0].get("webDetection"))

    def _parse(self, web: object) -> list[Candidate]:
        if not isinstance(web, dict):
            return []
        candidates: list[Candidate] = []
        seen_images: set[str] = set()
        for page in _dict_items(web.get("pagesWithMatchingImages")):
            page_url = clean_url(page.get("url"))
            if not page_url:
                continue
            full = [clean_url(i.get("url")) for i in _dict_items(page.get("fullMatchingImages"))]
            partial = [clean_url(i.get("url")) for i in _dict_items(page.get("partialMatchingImages"))]
            full, partial = [u for u in full if u], [u for u in partial if u]
            match_type = MatchType.EXACT if full else MatchType.PARTIAL
            image_url = (full or partial or [None])[0]
            if image_url:
                seen_images.add(image_url)
            candidates.append(
                Candidate(self.name, match_type, page_url, clean_text(page.get("pageTitle")), image_url)
            )
        for key, match_type in (
            ("fullMatchingImages", MatchType.EXACT),
            ("partialMatchingImages", MatchType.PARTIAL),
            # Useful for edited images: the unedited picture may only show up here.
            ("visuallySimilarImages", MatchType.SIMILAR),
        ):
            for item in _dict_items(web.get(key)):
                image_url = clean_url(item.get("url"))
                if image_url and image_url not in seen_images:
                    seen_images.add(image_url)
                    candidates.append(Candidate(self.name, match_type, image_url=image_url))
        return candidates


class TinEye:
    """TinEye REST API, called directly with the fields the official client uses.

    The official pytineye 3.0.0 client pins urllib3==1.26.6, certifi==2021.5.30 and
    future==0.18.2, which are too old to install beside the API's dependencies.
    """

    name = "tineye"
    url = "https://api.tineye.com/rest/search/"

    def __init__(self, api_key: str) -> None:
        self._key = api_key

    def search(self, upload: Upload, http: RequestFunction, config: ProvenanceConfig) -> list[Candidate]:
        fields = {"offset": "0", "limit": str(config.max_results_per_provider), "sort": "crawl_date", "order": "asc"}
        body, content_type = _multipart(fields, "image_upload", upload.jpeg(_DEFAULT_UPLOAD_LIMIT))
        payload = _call_json(
            self.name,
            http,
            self.url,
            config,
            method="POST",
            headers={"Content-Type": content_type, "x-api-key": self._key},
            body=body,
        )
        if payload.get("code") != 200:
            raise ProviderFailure(f"{self.name} could not process this image.")
        results = payload.get("results")
        matches = results.get("matches") if isinstance(results, dict) else None
        return [
            candidate
            for match in _dict_items(matches)
            for candidate in self._parse_match(match)
        ]

    def _parse_match(self, match: dict) -> list[Candidate]:
        candidates = []
        for link in _dict_items(match.get("backlinks")):
            page_url = clean_url(link.get("backlink"))
            image_url = clean_url(link.get("url")) or clean_url(match.get("image_url"))
            if not page_url and not image_url:
                continue
            candidates.append(
                Candidate(
                    self.name,
                    MatchType.PARTIAL,
                    page_url,
                    image_url=image_url,
                    crawl_date=_parse_crawl_date(link.get("crawl_date")),
                    decide_type_by_phash=True,
                )
            )
        return candidates


def _parse_crawl_date(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class SerpApiLens:
    """SerpApi Google Lens exact matches. Its dates are relative, such as "2 years ago"."""

    name = "serpapi_google_lens"
    upload_url = "https://serpapi.com/image"
    search_url = "https://serpapi.com/search"

    def __init__(self, api_key: str) -> None:
        self._key = api_key

    def search(self, upload: Upload, http: RequestFunction, config: ProvenanceConfig) -> list[Candidate]:
        # SerpApi takes its key as a field. http never logs URLs or puts them in errors.
        body, content_type = _multipart(
            {"api_key": self._key}, "image", upload.jpeg(_SERPAPI_UPLOAD_LIMIT)
        )
        uploaded = _call_json(
            self.name, http, self.upload_url, config, method="POST", headers={"Content-Type": content_type}, body=body
        )
        image_id = uploaded.get("image_id")
        if not isinstance(image_id, str) or not image_id:
            raise ProviderFailure(f"{self.name} could not accept this image.")
        query = urlencode(
            {"engine": "google_lens", "type": "exact_matches", "image_id": image_id, "api_key": self._key}
        )
        payload = _call_json(self.name, http, f"{self.search_url}?{query}", config)
        error = payload.get("error")
        if isinstance(error, str) and _NO_RESULTS_MARKER not in error:
            raise ProviderFailure(f"{self.name} could not complete the search.")
        candidates = []
        for item in _dict_items(payload.get("exact_matches"))[: config.max_results_per_provider]:
            page_url = clean_url(item.get("link"))
            if page_url:
                candidates.append(
                    Candidate(
                        self.name,
                        MatchType.EXACT,
                        page_url,
                        clean_text(item.get("title")),
                        clean_url(item.get("thumbnail")),
                        provider_date_text=clean_text(item.get("date"), limit=40),
                    )
                )
        return candidates


def configured_providers(config: ProvenanceConfig) -> list[Provider]:
    providers: list[Provider] = []
    if config.vision_api_key:
        providers.append(GoogleVisionWeb(config.vision_api_key))
    if config.tineye_api_key:
        providers.append(TinEye(config.tineye_api_key))
    if config.serpapi_api_key:
        providers.append(SerpApiLens(config.serpapi_api_key))
    return providers
