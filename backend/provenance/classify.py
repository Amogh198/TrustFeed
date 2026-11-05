"""Cleaning untrusted strings, normalizing URLs and sorting domains into platforms."""

from __future__ import annotations

import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from backend.provenance.models import Platform

_MAX_TEXT = 300
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_NAMES = {"fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "ref_src", "si"}

_SOCIAL = {
    "bsky.app", "facebook.com", "fb.com", "instagram.com", "linkedin.com", "mastodon.social", "pinterest.com",
    "reddit.com", "t.me", "telegram.me", "threads.net", "tiktok.com", "tumblr.com", "twitter.com", "vk.com",
    "x.com", "youtu.be", "youtube.com",
}
_NEWS = {
    "aajtak.in", "afp.com", "aljazeera.com", "apnews.com", "bbc.co.uk", "bbc.com", "cnn.com", "dailymail.co.uk",
    "deccanherald.com", "economictimes.indiatimes.com", "firstpost.com", "guardian.co.uk", "hindustantimes.com",
    "indianexpress.com", "indiatoday.in", "news18.com", "ndtv.com", "nytimes.com", "prajavani.net", "reuters.com",
    "scroll.in", "telegraph.co.uk", "theguardian.com", "thehindu.com", "theprint.in", "thequint.com", "thewire.in",
    "timesofindia.indiatimes.com", "washingtonpost.com",
}


def clean_text(value: object, limit: int = _MAX_TEXT) -> str | None:
    """Keep text from the web as inert display text: no control or hidden format characters."""
    if not isinstance(value, str):
        return None
    kept = "".join(ch if unicodedata.category(ch)[0] != "C" else " " for ch in value)
    collapsed = " ".join(kept.split())
    return collapsed[:limit] or None


def clean_url(value: object) -> str | None:
    """Return the URL only if it is a plain http or https link safe to show as a link."""
    if not isinstance(value, str) or len(value) > 2048:
        return None
    candidate = value.strip()
    if any(ord(ch) <= 0x20 or ord(ch) == 0x7F for ch in candidate):
        return None
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return None
    if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    return candidate


def dedupe_key(url: str) -> str:
    """Treat links to one page as equal, ignoring case of host, tracking tags and fragments."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    query = [
        (name, value)
        for name, value in parse_qsl(parts.query, keep_blank_values=True)
        if not name.lower().startswith(_TRACKING_PREFIXES) and name.lower() not in _TRACKING_NAMES
    ]
    return urlunsplit(("", host, parts.path.rstrip("/"), urlencode(sorted(query)), ""))


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    host = urlsplit(url).hostname
    return host.lower().removeprefix("www.") if host else None


def _matches(domain: str, names: set[str]) -> bool:
    return any(domain == name or domain.endswith("." + name) for name in names)


def classify_platform(domain: str | None, *, is_news_article: bool = False) -> Platform:
    if not domain:
        return Platform.UNKNOWN
    if _matches(domain, _SOCIAL):
        return Platform.SOCIAL
    if is_news_article or _matches(domain, _NEWS):
        return Platform.NEWS
    return Platform.WEB
