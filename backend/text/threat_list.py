"""Check a link against a list of reported phishing links held on this machine, so the link is never sent anywhere.

The list is Phishing.Database's file of active phishing links (MIT licence), which needs no key. It comes from
``python -m backend.text download-threat-list`` and is never downloaded during an analysis.
"""

from __future__ import annotations

import logging
import os
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from backend.api.app.models import LinkSign, LinkThreatLists, ModuleStatus

logger = logging.getLogger(__name__)

THREAT_LIST_URL = "https://raw.githubusercontent.com/Phishing-Database/Phishing.Database/master/phishing-links-ACTIVE.txt"
LIST_NAME = "Phishing.Database"
_MAX_BYTES = 150 * 1024 * 1024
_TIMEOUT_S = 120
NOT_SET_UP = "No phishing list has been downloaded. Run: python -m backend.text download-threat-list"


def threat_list_path() -> Path:
    configured = os.environ.get("THREAT_LIST_PATH")
    return Path(configured) if configured else Path.home() / ".cache" / "trustfeed" / "phishing_links_active.txt"


def _normal(url: str) -> str:
    parts = urlsplit(url.strip())
    query = f"?{parts.query}" if parts.query else ""
    return f"{parts.scheme.casefold()}://{parts.netloc.casefold()}{parts.path.rstrip('/')}{query}"


def _look_up(path: Path, url: str, host: str) -> tuple[bool, bool]:
    """Scan the file for the link, without holding millions of addresses in memory between checks."""
    wanted = _normal(url)
    host_listed = False
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if host not in line or line.startswith("#"):
                continue
            try:
                if urlsplit(line.strip()).hostname != host:
                    continue
                if _normal(line) == wanted:
                    return True, True
            except ValueError:
                continue
            host_listed = True
    return False, host_listed


def check_threat_list(url: str, host: str, known_official: bool) -> tuple[LinkThreatLists, list[LinkSign]]:
    """Look a link up locally. A listed host alone is weak, since a hacked honest site can be listed."""
    path = threat_list_path()
    if not path.is_file():
        return LinkThreatLists(status=ModuleStatus.UNAVAILABLE, reason=NOT_SET_UP), []
    try:
        exact, host_listed = _look_up(path, url, host.casefold()) if host else (False, False)
        saved = datetime.fromtimestamp(path.stat().st_mtime, UTC).date().isoformat()
    except (OSError, ValueError) as exc:
        logger.warning("The phishing list could not be read: %s", type(exc).__name__)
        return LinkThreatLists(status=ModuleStatus.UNAVAILABLE, reason="The phishing list could not be read."), []
    reason = f"{LIST_NAME} list saved on {saved}. The link wasn't sent anywhere. A link not being listed doesn't make it safe."
    status = LinkThreatLists(status=ModuleStatus.COMPLETE, reason=reason)
    if exact:
        return status, [LinkSign(sign="listed_on_threat_list", strength="strong", why=f"This exact address is on the {LIST_NAME} list of reported phishing links.")]
    if host_listed and not known_official:
        return status, [LinkSign(sign="host_on_threat_list", strength="weak", why=f"Another address on {host} is on the {LIST_NAME} list of reported phishing links.")]
    return status, []


def download_threat_list() -> tuple[Path, int]:
    """Save the current list. Analysis never calls this."""
    path = threat_list_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(THREAT_LIST_URL, headers={"User-Agent": "TrustFeed-LinkCheck/1.0"})
    with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as response:
        body = response.read(_MAX_BYTES + 1)
    if len(body) > _MAX_BYTES:
        raise ValueError("The phishing list is larger than expected.")
    partial = path.with_suffix(".part")
    partial.write_bytes(body)
    partial.replace(path)
    count = sum(1 for line in body.decode("utf-8", "replace").splitlines() if line.strip() and not line.startswith("#"))
    return path, count
