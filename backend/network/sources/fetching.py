"""Ways to get a platform response: live, recorded for later, or replayed offline."""

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from backend.network.sources.base import Fetch, FetchError

_TIMEOUT_SECONDS = 10
_MAX_RESPONSE_BYTES = 5_000_000
# A generic client name, with nothing that identifies a user.
_HEADERS = {"User-Agent": "TrustFeed/0.1", "Accept": "application/json"}


def live_fetch(url: str) -> Any:
    """Read JSON from a public HTTPS endpoint. Adapters build these URLs for fixed hosts only."""
    if not url.startswith("https://"):
        raise FetchError("Only HTTPS endpoints are read")
    request = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            body = response.read(_MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise FetchError(f"The platform refused the request (HTTP {error.code})", error.code) from error
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise FetchError("The platform could not be reached") from error
    if len(body) > _MAX_RESPONSE_BYTES:
        raise FetchError("The platform's response was too large")
    try:
        return json.loads(body)
    except ValueError as error:
        raise FetchError("The platform's response was not valid JSON") from error


class Budgeted:
    """Stop fetching after a time limit, so a slow platform can't hold up a whole case."""

    def __init__(self, fetch: Fetch, seconds: float) -> None:
        self._fetch = fetch
        self._deadline = time.monotonic() + seconds
        # Keep the wrapped fetch's labels, so a replay still says it's a replay.
        for name in ("synthetic", "recorded_at", "mode"):
            if hasattr(fetch, name):
                setattr(self, name, getattr(fetch, name))

    def __call__(self, url: str) -> Any:
        if time.monotonic() > self._deadline:
            raise FetchError("The time limit for this trace was reached")
        return self._fetch(url)


class ReplayFetch:
    """Serve recorded responses offline, so a demo needs no internet or platform."""

    def __init__(self, path: Path) -> None:
        with path.open(encoding="utf-8") as handle:
            recording = json.load(handle)
        self.synthetic: bool = recording.get("synthetic") is True
        self.recorded_at: str | None = recording.get("recorded_at")
        self.mode = "replay"
        self._responses: dict[str, Any] = recording.get("responses", {})

    def __call__(self, url: str) -> Any:
        if url not in self._responses:
            raise FetchError("This request is not in the recording")
        return self._responses[url]


class RecordingFetch:
    """Fetch live and keep each response, so a run can be replayed later with ``ReplayFetch``.

    Recordings hold real people's public posts. Save them under a git-ignored
    folder such as ``backend/network/recordings/`` and never commit them.
    """

    def __init__(self, fetch: Fetch = live_fetch) -> None:
        self._fetch = fetch
        self.responses: dict[str, Any] = {}

    def __call__(self, url: str) -> Any:
        response = self._fetch(url)
        self.responses[url] = response
        return response

    def save(self, path: Path, recorded_at: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        document = {"synthetic": False, "recorded_at": recorded_at, "responses": self.responses}
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
