from urllib.parse import urlsplit

from backend.api.app.models import ModuleResult, ModuleStatus, RiskLevel


URGENT_PHRASES = (
    "act now", "urgent", "immediately", "limited time", "before it is deleted",
    "forward this", "share this now", "breaking",
)
SCAM_PHRASES = (
    "claim your prize", "guaranteed returns", "send your password", "verify your account",
    "wire the fee", "pay processing fee", "free gift card",
)
SHORTENER_HOSTS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "ow.ly"}
SUSPICIOUS_TLDS = {".zip", ".mov", ".click", ".top", ".work"}


def analyze_text(text: str) -> tuple[ModuleResult, list[str]]:
    normalized = text.casefold()
    evidence: list[str] = []
    for phrase in URGENT_PHRASES:
        if phrase in normalized:
            evidence.append(f"Urgency language detected: {phrase!r}")
    for phrase in SCAM_PHRASES:
        if phrase in normalized:
            evidence.append(f"Known scam-pattern phrase detected: {phrase!r}")
    if text.count("!") >= 3:
        evidence.append("Multiple exclamation marks may indicate high-pressure language")

    score = min(1.0, 0.15 * sum("Urgency" in item for item in evidence)
                + 0.3 * sum("scam-pattern" in item for item in evidence)
                + 0.1 * sum("exclamation" in item for item in evidence))
    result = ModuleResult(
        status=ModuleStatus.COMPLETE,
        score=round(score, 2),
        confidence=None,
        evidence=evidence,
        limitations=["Rule-based language signals do not verify whether factual claims are true."],
    )
    claims = [text.strip()] if text.strip() else []
    return result, claims


def analyze_url(url: str) -> ModuleResult:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").casefold().rstrip(".")
    evidence: list[str] = []
    if parsed.scheme != "https":
        evidence.append("URL does not use HTTPS")
    if parsed.username or parsed.password:
        evidence.append("URL contains embedded user information")
    if host in SHORTENER_HOSTS:
        evidence.append("URL uses a known shortening domain; destination was not expanded")
    if any(host.endswith(tld) for tld in SUSPICIOUS_TLDS):
        evidence.append("Domain uses a TLD that can appear in deceptive links")
    if host.startswith("xn--") or ".xn--" in host:
        evidence.append("Domain contains an internationalized (punycode) label")
    if host.count("-") >= 3:
        evidence.append("Domain contains several hyphens")

    score = min(1.0, 0.2 * len(evidence))
    return ModuleResult(
        status=ModuleStatus.COMPLETE,
        score=round(score, 2),
        confidence=None,
        evidence=evidence,
        limitations=["Static URL heuristics only; no domain reputation or destination fetch was performed."],
    )


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
