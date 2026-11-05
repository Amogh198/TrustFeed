"""Deterministic text and URL signal extraction.

These are fixed rules, not a trained model, and they have not been measured on labelled
data. They flag common patterns for a person to review and never verify a claim.
"""
import ipaddress
import re
from collections.abc import Callable
from urllib.parse import urlsplit

from backend.api.app.models import ModuleResult, ModuleStatus, RiskLevel
from backend.provenance.safe_http import HttpBlocked, HttpFailed, safe_request

# (evidence wording, weight per phrase, most this category can add, phrases)
_TEXT_CATEGORIES = (
    (
        "Urgency language detected",
        0.15,
        0.45,
        (
            "act now", "urgent", "immediately", "limited time", "before it is deleted", "before this is deleted",
            "forward this", "forward to everyone", "share this now", "share now", "share before", "breaking",
            "तुरंत", "फौरन", "सबको भेजें", "सब को भेजें", "शेयर करें", "फॉरवर्ड करें",
        ),
    ),
    (
        "Known scam-pattern phrase detected",
        0.35,
        0.75,
        (
            "claim your prize", "claim your reward", "you have won", "guaranteed returns", "double your money",
            "send your password", "verify your account", "wire the fee", "pay processing fee", "free gift card",
            "otp", "one-time password", "bank details", "card number", "click here to claim",
            "इनाम जीता", "ओटीपी", "बैंक खाता", "पैसे दोगुने",
        ),
    ),
    (
        "Suppression or conspiracy framing detected",
        0.2,
        0.4,
        (
            "officials are hiding", "hiding the truth", "media will not tell you", "media won't tell you",
            "do not want you to know", "don't want you to know", "was rigged", "cover-up", "cover up",
            "छिपा रहे", "सच छुपा",
        ),
    ),
    (
        "Unsupported health claim pattern detected",
        0.3,
        0.6,
        ("cures the virus", "cures cancer", "miracle cure", "drinking bleach", "drink bleach", "जहर मिला"),
    ),
)
# Rules can't check whether anything is true, so on their own they never reach critical.
_MAX_RULE_SCORE = 0.75
SHORTENER_HOSTS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "ow.ly", "rb.gy", "cutt.ly", "shorturl.at"}
SUSPICIOUS_TLDS = {".zip", ".mov", ".click", ".top", ".work"}
# Names often impersonated in phishing links, and the domains that really are theirs.
_BRANDS = {
    "paypal": ("paypal.com",),
    "google": ("google.com", "google.co.in"),
    "facebook": ("facebook.com",),
    "instagram": ("instagram.com",),
    "whatsapp": ("whatsapp.com",),
    "amazon": ("amazon.com", "amazon.in"),
    "apple": ("apple.com",),
    "microsoft": ("microsoft.com",),
    "netflix": ("netflix.com",),
    "paytm": ("paytm.com",),
    "phonepe": ("phonepe.com",),
    "hdfc": ("hdfcbank.com",),
    "icici": ("icicibank.com",),
    "sbi": ("sbi.co.in", "onlinesbi.sbi", "sbi.bank.in"),
}
_TWO_PART_SUFFIXES = {"co.in", "co.uk", "com.au", "gov.in", "org.in", "net.in", "ac.in", "bank.in"}
_LOOKALIKE_DIGITS = str.maketrans({"0": "o", "1": "l", "3": "e", "5": "s", "@": "a"})
_CREDENTIAL_WORDS = re.compile(r"login|log-in|signin|sign-in|verify|password|account|otp|kyc", re.IGNORECASE)
_CLAIM_BOUNDARY = re.compile(r"(?<=[.!?।])\s+|\n+")
_MAX_CLAIMS = 20
_EXPAND_TIMEOUT_SECONDS = 4.0


def extract_claims(text: str) -> list[str]:
    """Split input into sentence-like units for separate evidence follow-up.

    This is deterministic atomization, not fact checking. A compact fallback keeps
    an unpunctuated post visible as one claim instead of silently discarding it.
    """
    candidates = [part.strip() for part in _CLAIM_BOUNDARY.split(text) if part.strip()]
    return (candidates or [text.strip()])[:_MAX_CLAIMS] if text.strip() else []


def _contains(text: str, phrase: str) -> bool:
    """Match whole words, so "otp" isn't found inside "hotpot" or "urgent" inside "insurgent"."""
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def analyze_text(text: str) -> tuple[ModuleResult, list[str]]:
    normalized = text.casefold()
    evidence: list[str] = []
    score = 0.0
    for wording, weight, most, phrases in _TEXT_CATEGORIES:
        found = [phrase for phrase in phrases if _contains(normalized, phrase)]
        evidence.extend(f"{wording}: {phrase!r}" for phrase in found)
        score += min(most, weight * len(found))
    if text.count("!") >= 3:
        evidence.append("Multiple exclamation marks may indicate high-pressure language")
        score += 0.1

    result = ModuleResult(
        status=ModuleStatus.COMPLETE,
        score=round(min(_MAX_RULE_SCORE, score), 2),
        confidence=None,
        evidence=evidence,
        limitations=[
            "Rule-based language signals do not verify whether factual claims are true.",
            "Fixed phrase lists miss rewording and most languages. Finding nothing does not make content safe.",
        ],
    )
    return result, extract_claims(text)


def _registered_domain(host: str) -> str:
    labels = host.split(".")
    size = 3 if ".".join(labels[-2:]) in _TWO_PART_SUFFIXES else 2
    return ".".join(labels[-size:])


def _impersonated_brand(host: str) -> str | None:
    """Name a brand this host seems to imitate, or None if the host really belongs to it."""
    registered = _registered_domain(host)
    plain = host.translate(_LOOKALIKE_DIGITS)
    for brand, official in _BRANDS.items():
        if registered in official or any(host.endswith(f".{domain}") for domain in official):
            continue
        if re.search(rf"(?<![a-z]){brand}(?![a-z])", plain):
            return brand
    return None


def _url_signals(url: str) -> tuple[list[str], float]:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold().rstrip(".")
    signals: list[tuple[str, float]] = []
    if parsed.scheme != "https":
        signals.append(("URL does not use HTTPS", 0.2))
    if parsed.username or parsed.password:
        signals.append(("URL contains embedded user information", 0.4))
    if host in SHORTENER_HOSTS:
        signals.append(("URL uses a known shortening domain, which hides its destination", 0.3))
    if any(host.endswith(tld) for tld in SUSPICIOUS_TLDS):
        signals.append(("Domain uses a TLD that can appear in deceptive links", 0.2))
    if host.startswith("xn--") or ".xn--" in host:
        signals.append(("Domain contains an internationalized (punycode) label", 0.3))
    if host.count("-") >= 3:
        signals.append(("Domain contains several hyphens", 0.2))
    try:
        ipaddress.ip_address(host)
        signals.append(("URL points at a bare IP address instead of a domain name", 0.4))
    except ValueError:
        brand = _impersonated_brand(host)
        if brand:
            signals.append((f"Domain includes the name {brand!r} but does not belong to it", 0.5))
    if signals and _CREDENTIAL_WORDS.search(f"{host}{parsed.path}"):
        signals.append(("Link also asks for a login or account details", 0.15))
    return [wording for wording, _ in signals], sum(weight for _, weight in signals)


def analyze_url(url: str, expanded_to: str | None = None) -> ModuleResult:
    """Score a link. ``expanded_to`` is its destination, when an opted-in request followed it."""
    evidence, score = _url_signals(url)
    limitation = "Static URL heuristics only; no domain reputation source was checked."
    if expanded_to:
        final_evidence, final_score = _url_signals(expanded_to)
        host = urlsplit(expanded_to).hostname or "an unknown host"
        evidence = [*evidence, f"The short link leads to {host}", *(f"Destination: {item}" for item in final_evidence)]
        score += final_score
    elif urlsplit(url).hostname in SHORTENER_HOSTS:
        evidence.append("The destination was not followed, as the user did not opt in to outside requests")
    return ModuleResult(
        status=ModuleStatus.COMPLETE,
        score=round(min(_MAX_RULE_SCORE, score), 2),
        confidence=None,
        evidence=evidence,
        limitations=[limitation],
    )


def expand_shortener(url: str, request: Callable[..., object] = safe_request) -> str | None:
    """Follow a known shortener to its destination. Call only when the user has opted in.

    This uses the same protected HTTP as source search, which refuses private addresses.
    Any failure returns None, as the link is then scored without its destination.
    """
    if (urlsplit(url).hostname or "").casefold() not in SHORTENER_HOSTS:
        return None
    try:
        response = request(url, method="GET", timeout_s=_EXPAND_TIMEOUT_SECONDS, max_bytes=4096)
    except (HttpBlocked, HttpFailed):
        return None
    final = getattr(response, "url", None)
    return final if isinstance(final, str) and final != url else None


def fuse_risk(text_result: ModuleResult | None, url_result: ModuleResult | None) -> RiskLevel:
    available = [r.score for r in (text_result, url_result) if r and r.score is not None]
    if not available:
        return RiskLevel.INCONCLUSIVE
    score = max(available)
    if score >= 0.8:
        return RiskLevel.CRITICAL
    if score >= 0.6:
        return RiskLevel.HIGH
    if score >= 0.3:
        return RiskLevel.MODERATE
    return RiskLevel.LOW


def signal_summary(level: RiskLevel) -> str:
    if level == RiskLevel.INCONCLUSIVE:
        return "No analyzable text or URL signals were available."
    return f"Rule-based indicators suggest {level.value} risk; this is a triage signal, not a factual verdict."
