"""Look into a submitted link: where it goes, how old it is, what the page asks for, who it imitates.

The lookalike check needs no outside request. Everything else contacts the link or a public
registry, so it runs only when the user has allowed outside requests. Pages are read as data,
never run, and only a short title leaves this module. A part that could not run says why, and
is never reported as having found nothing.

These rules were written by hand. See ``backend/text/evaluation/results/link_eval_test.json``
for what was measured, which is the offline part only.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit

from backend.api.app.models import (
    LinkAnalysis,
    LinkDomainAge,
    LinkHop,
    LinkLookalike,
    LinkOfficialComparison,
    LinkPage,
    LinkRedirects,
    LinkSign,
    LinkThreatLists,
    ModuleStatus,
)
from backend.provenance.safe_http import (
    HttpBlocked,
    HttpFailed,
    HttpResponse,
    safe_request,
)
from backend.text.analysis import _BRANDS, SHORTENER_HOSTS, _registered_domain
from backend.text.scams import NONE_FOUND, WARNING_SIGNS, WEAK_ONLY

RESULTS_FILE = "backend/text/evaluation/results/link_eval_test.json"
RDAP_URL = "https://rdap.org/domain/{domain}"
_HEADERS = {"User-Agent": "TrustFeed-LinkCheck/1.0", "Accept": "text/html,application/xhtml+xml,*/*;q=0.5"}
_REDIRECTS = {301, 302, 303, 307, 308}
_MAX_HOPS = 6
# Home pages of large sites really do reach a megabyte or more.
_MAX_PAGE_BYTES = 3 * 1024 * 1024
_REQUEST_TIMEOUT_S = 5.0
_TOTAL_BUDGET_S = 20.0
_MAX_TITLE = 200
# Only the first part of a page is read, as parsing a crafted page can be slow.
_MAX_PARSE_CHARS = 512 * 1024
_PARSE_CHUNK = 32 * 1024
_MAX_PARSE_SECONDS = 2.0
_NEW_DOMAIN_DAYS = 30
_YOUNG_DOMAIN_DAYS = 180
_SIMILAR_TITLE = 0.6
_MIN_TYPO_BRAND = 6
_MANY_HOPS = 4

_FAILURE_REASONS = {
    "timeout": "The site did not answer in time.",
    "network": "The site could not be reached, or its security certificate could not be verified.",
    "too_large": "The page was too large to read.",
    "decode": "The page's content could not be decoded.",
}
# Letters from other alphabets that look the same as Latin ones.
_CONFUSABLES = str.maketrans(
    {
        "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ѕ": "s", "ԁ": "d",
        "һ": "h", "ո": "n", "ɡ": "g", "ⅼ": "l", "ı": "i", "ʟ": "l", "ο": "o", "α": "a", "ν": "v", "ρ": "p",
    }
)
_DIGITS = str.maketrans({"0": "o", "1": "l", "3": "e", "5": "s", "4": "a", "7": "t"})
# Words attackers add to a brand's name to make a domain look like its support or login site.
_PRETEXT_WORDS = {
    "secure", "security", "login", "signin", "verify", "verification", "account", "accounts", "support", "update",
    "help", "online", "official", "service", "services", "customer", "care", "kyc", "reward", "rewards", "bonus",
    "refund", "wallet", "auth", "billing", "confirm", "alert", "recovery", "web", "portal", "mail",
}
_CARD_FIELD = re.compile(r"card.?(num|no\b)|cc.?num|cvv|cvc|expiry|exp.?date|(^|[^a-z])upi([^a-z]|$)|ifsc|account.?(num|no\b)", re.IGNORECASE)
_CODE_FIELD = re.compile(r"(^|[^a-z])otp([^a-z]|$)|one.?time|atm.?pin|(^|[^a-z])m?pin([^a-z]|$)", re.IGNORECASE)
_VALID_HOST = re.compile(r"^[a-z0-9.-]{1,253}$")
_REFRESH = re.compile(r"url\s*=\s*['\"]?([^'\";>\s]+)", re.IGNORECASE)

LIMITATIONS = [
    "A warning sign is a reason to look closer, not proof of a scam. Finding none does not make a link safe.",
    "Page scripts are not run, and a site can show this check something different from what people see.",
    "The list of official domains covers only a few well-known names, so most imitations can't be recognised here.",
    "No threat list was consulted, so a link already reported as malicious would not be recognised.",
]
THREAT_LIST_REASON = "No threat list is set up. Safe Browsing and URLhaus need keys that have not been created."

Request = Callable[..., HttpResponse]


def _safe_url(url: str) -> str:
    """Keep the address without its query or user details, which can hold private tokens."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    return f"{parts.scheme}://{host}{parts.path}"[:300]


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").casefold().rstrip(".")
    except ValueError:
        return ""


def _join(base: str, target: str) -> str | None:
    """Resolve an address the page wrote, which can be malformed on purpose."""
    try:
        joined = urljoin(base, target)
        urlsplit(joined).port  # noqa: B018 - Reading the port is what checks it.
    except ValueError:
        return None
    return joined


def _is_ip(host: str) -> bool:
    return host.replace(".", "").isdigit() or ":" in host


def _owned_brand(host: str) -> str | None:
    registered = _registered_domain(host)
    for brand, official in _BRANDS.items():
        if registered in official or any(host.endswith(f".{domain}") for domain in official):
            return brand
    return None


def _decode_label(label: str) -> str:
    if not label.startswith("xn--"):
        return label
    try:
        return label.encode("ascii").decode("idna")
    except (UnicodeError, ValueError):
        return label


def _one_edit_apart(left: str, right: str) -> bool:
    """True for one changed, added, removed or swapped letter."""
    if left == right or abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        changed = [i for i, (a, b) in enumerate(zip(left, right)) if a != b]
        if len(changed) == 1:
            return True
        return (
            len(changed) == 2
            and changed[1] == changed[0] + 1
            and left[changed[0]] == right[changed[1]]
            and left[changed[1]] == right[changed[0]]
        )
    short, long = sorted((left, right), key=len)
    return any(long[:i] + long[i + 1 :] == short for i in range(len(long)))


def _subdomain_match(brand: str, labels: list[str]) -> tuple[str, str] | None:
    """Anyone can name a subdomain anything, so a plain name is weak and added pretext words are strong."""
    for label in labels:
        words = re.split(r"[-_]", label.translate(_CONFUSABLES).translate(_DIGITS))
        if brand in words:
            if len(words) > 1 and all(word == brand or word in _PRETEXT_WORDS for word in words):
                return ("strong", "has a subdomain adding account or support words to")
            return ("weak", "has a subdomain named after")
    return None


def find_lookalike(host: str) -> LinkLookalike:
    """Say whether a host imitates a known brand. Uses the address alone, so it is always available."""
    host = host.casefold().rstrip(".")
    empty = LinkLookalike(status=ModuleStatus.COMPLETE, host=host)
    if not host or _is_ip(host):
        return empty
    owner = _owned_brand(host)
    if owner:
        return empty.model_copy(update={"owned_by": owner, "official_domains": list(_BRANDS[owner])})
    labels = [_decode_label(label) for label in host.split(".")]
    registered_size = len(_registered_domain(host).split("."))
    name = labels[-registered_size]
    plain = name.translate(_CONFUSABLES)
    swapped = plain.translate(_DIGITS)
    joined = ".".join(labels)
    for brand, official in _BRANDS.items():
        match: tuple[str, str] | None = None
        words = re.split(r"[-_]", swapped)
        extra = swapped.replace(brand, "", 1).strip("-_") if brand in swapped else None
        if plain != name and plain == brand:
            match = ("strong", "uses letters from another alphabet that look like")
        elif swapped != name and swapped == brand:
            match = ("strong", "swaps letters for digits to look like")
        elif swapped.replace("rn", "m").replace("vv", "w") == brand and swapped != brand:
            match = ("strong", "uses paired letters to look like")
        elif len(brand) >= _MIN_TYPO_BRAND and _one_edit_apart(swapped, brand):
            match = ("strong", "is one letter away from")
        elif any(joined.startswith(f"{domain}.") or f".{domain}." in joined for domain in official):
            match = ("strong", "puts the official address at the front of a different domain, imitating")
        elif brand in words and len(words) > 1:
            pretext = all(word == brand or word in _PRETEXT_WORDS for word in words)
            match = ("strong", "adds account or support words to") if pretext else ("weak", "includes the name")
        elif len(brand) >= 4 and extra in _PRETEXT_WORDS:
            match = ("strong", "adds an account or support word to")
        elif swapped == brand:
            match = ("weak", "has the same name but a domain not on our short official list for")
        else:
            match = _subdomain_match(brand, labels[:-registered_size])
        if match:
            return empty.model_copy(
                update={"strength": match[0], "how": match[1], "brand": brand, "official_domains": list(official)}
            )
    return empty


class _PageReader(HTMLParser):
    """Collect the title, visible words, forms and any refresh redirect. Nothing here is run."""

    _HIDDEN = frozenset({"script", "style", "noscript", "template", "svg"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: list[str] = []
        self.text: list[str] = []
        self.forms: list[str] = []
        self.refresh: str | None = None
        self.has_password = False
        self.has_card = False
        self.has_code = False
        self.script_tags = 0
        self._in_title = False
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.casefold(): (value or "") for name, value in attrs}
        if tag == "title":
            # A drawing can hold its own title, and only the page's first one counts.
            self._in_title = not self._hidden_depth and not self.title
        elif tag in self._HIDDEN:
            self._hidden_depth += 1
            self.script_tags += tag == "script"
        elif tag == "form":
            self.forms.append(values.get("action", ""))
        elif tag == "meta" and values.get("http-equiv", "").casefold() == "refresh":
            found = _REFRESH.search(values.get("content", ""))
            self.refresh = self.refresh or (found.group(1) if found else None)
        elif tag == "input" and values.get("type", "").casefold() != "hidden":
            names = " ".join(values.get(key, "") for key in ("name", "id", "placeholder", "aria-label"))
            self.has_password = self.has_password or values.get("type", "").casefold() == "password"
            filled = values.get("autocomplete", "").casefold()
            self.has_card = self.has_card or filled.startswith("cc-") or bool(_CARD_FIELD.search(names))
            self.has_code = self.has_code or filled == "one-time-code" or bool(_CODE_FIELD.search(names))

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in self._HIDDEN and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title.append(data)
        elif not self._hidden_depth:
            self.text.append(data)


def _charset(response: HttpResponse) -> str:
    found = re.search(r"charset=['\"]?([\w-]+)", response.headers.get("content-type", ""), re.IGNORECASE)
    return found.group(1) if found else "utf-8"


def _read_page(response: HttpResponse) -> _PageReader | None:
    """Read the page's first part, stopping at a time limit. A page that breaks the parser returns None."""
    reader = _PageReader()
    try:
        body = response.body.decode(_charset(response), errors="replace")
    except (LookupError, ValueError):
        body = response.body.decode("utf-8", errors="replace")
    body = body[:_MAX_PARSE_CHARS]
    limit = time.monotonic() + _MAX_PARSE_SECONDS
    try:
        for start in range(0, len(body), _PARSE_CHUNK):
            if time.monotonic() > limit:
                break
            reader.feed(body[start : start + _PARSE_CHUNK])
        reader.close()
    except Exception:  # noqa: BLE001 - A hostile page must not lose the rest of the report.
        return None
    return reader


def _is_html(response: HttpResponse) -> bool:
    kind = response.headers.get("content-type", "").casefold()
    return "html" in kind or not kind


def _clean_title(raw: list[str]) -> str | None:
    printable = "".join(ch for ch in "".join(raw) if ch.isprintable() or ch.isspace())
    return re.sub(r"\s+", " ", printable).strip()[:_MAX_TITLE] or None


def _words(text: str) -> set[str]:
    return {word for word in re.findall(r"[^\W\d_]{3,}", text.casefold())}


def _overlap(left: str, right: str) -> float:
    a, b = _words(left), _words(right)
    return round(len(a & b) / len(a | b), 2) if a and b else 0.0


class _Budget:
    """One time limit shared by every outside request for a link."""

    def __init__(self, request: Request, clock: Callable[[], float]) -> None:
        self._request = request
        self._clock = clock
        self._limit = clock() + _TOTAL_BUDGET_S

    def get(self, url: str, *, redirects: int = 0, headers: dict[str, str] | None = None) -> HttpResponse:
        if self._clock() >= self._limit:
            raise HttpFailed("timeout")
        return self._request(
            url,
            method="GET",
            headers=headers or _HEADERS,
            timeout_s=_REQUEST_TIMEOUT_S,
            max_bytes=_MAX_PAGE_BYTES,
            deadline=self._limit,
            max_redirects=redirects,
        )


def _follow(url: str, budget: _Budget) -> tuple[LinkRedirects, HttpResponse | None, _PageReader | None, str, bool]:
    """Walk the redirects one at a time, so every hop is seen and checked."""
    hops: list[LinkHop] = []
    current = url
    seen = {url}
    response: HttpResponse | None = None
    reader: _PageReader | None = None
    failure: str | None = None
    reached_failed = False
    unreadable = False
    for _ in range(_MAX_HOPS):
        try:
            response = budget.get(current)
        except HttpBlocked as exc:
            failure = f"Stopped by a safety rule: {exc}"
            response = None
            break
        except HttpFailed as exc:
            failure = _FAILURE_REASONS.get(exc.kind, "The request failed.")
            reached_failed = True
            response = None
            break
        hops.append(LinkHop(url=_safe_url(current), host=_host(current), status=response.status))
        location = response.headers.get("location")
        reader = None
        next_url: str | None = None
        if response.status in _REDIRECTS and location:
            next_url = _join(current, location)
            if next_url is None:
                failure = "The link redirects to a malformed address."
                response = None
                break
        elif response.status == 200 and _is_html(response):
            reader = _read_page(response)
            if reader is None:
                unreadable = True
            elif reader.refresh:
                # A page's refresh is optional, so a malformed one just isn't followed.
                next_url = _join(current, reader.refresh)
        if next_url is None:
            break
        if next_url in seen:
            failure = "The link redirects in a loop."
            response, reader = None, None
            break
        seen.add(next_url)
        current = next_url
        response, reader = None, None
    else:
        failure = "The link kept redirecting past the limit, so its destination is unknown."
    # A site that redirected here and then failed still shows where the link leads.
    known = failure is None or (reached_failed and bool(hops))
    final = _safe_url(current) if known else None
    status = ModuleStatus.COMPLETE if failure is None else ModuleStatus.UNAVAILABLE
    return (
        LinkRedirects(status=status, reason=failure, hops=hops, final_url=final, final_host=_host(current) if final else None),
        response,
        reader,
        current,
        unreadable,
    )


def _page_record(
    response: HttpResponse | None, reader: _PageReader | None, redirects: LinkRedirects, url: str, unreadable: bool = False
) -> LinkPage:
    if response is None:
        return LinkPage(status=ModuleStatus.UNAVAILABLE, reason=redirects.reason or "The page could not be read.")
    if unreadable:
        return LinkPage(status=ModuleStatus.UNAVAILABLE, reason="The page's content could not be read.", http_status=response.status)
    if response.status != 200:
        return LinkPage(
            status=ModuleStatus.UNAVAILABLE, reason=f"The site answered with error {response.status}.", http_status=response.status
        )
    if reader is None:
        kind = response.headers.get("content-type", "unknown").split(";")[0].strip()
        kind = "".join(ch for ch in kind if ch.isascii() and ch.isprintable())[:60] or "unknown"
        return LinkPage(
            status=ModuleStatus.NOT_APPLICABLE, reason=f"The link leads to a file of type {kind}, not a web page.", http_status=200
        )
    own_domain = _registered_domain(_host(url))
    posts_to = []
    for action in reader.forms:
        joined = _join(url, action) if action else None
        target = _host(joined) if joined else ""
        if not target:
            continue
        if not _VALID_HOST.match(target):
            # The page wrote this, so a strange value isn't repeated in the report.
            posts_to.append("an invalid address")
        elif _is_ip(target) or _registered_domain(target) != own_domain:
            posts_to.append(target)
    words = " ".join(reader.text)
    return LinkPage(
        status=ModuleStatus.COMPLETE,
        http_status=200,
        title=_clean_title(reader.title),
        asks_for_login=reader.has_password,
        asks_for_payment=reader.has_card,
        asks_for_code=reader.has_code,
        form_posts_to=sorted(set(posts_to))[:5],
        reason=(
            "The page shows little text and relies on scripts, which are not run, so its real content may not have been seen."
            if len(_words(words)) < 10 and reader.script_tags
            else None
        ),
    )


def _rdap_date(data: Any) -> datetime | None:
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        return None
    for event in data["events"]:
        if isinstance(event, dict) and event.get("eventAction") == "registration":
            try:
                found = datetime.fromisoformat(str(event.get("eventDate")))
            except ValueError:
                return None
            return found if found.tzinfo else found.replace(tzinfo=UTC)
    return None


def _domain_age(host: str, budget: _Budget, now: datetime) -> LinkDomainAge:
    if not host or _is_ip(host):
        return LinkDomainAge(status=ModuleStatus.NOT_APPLICABLE, reason="The link has no domain name to look up.")
    domain = _registered_domain(host)
    try:
        response = budget.get(
            RDAP_URL.format(domain=domain),
            redirects=3,
            headers={"User-Agent": _HEADERS["User-Agent"], "Accept": "application/rdap+json, application/json"},
        )
    except HttpBlocked as exc:
        return LinkDomainAge(status=ModuleStatus.UNAVAILABLE, domain=domain, reason=f"Stopped by a safety rule: {exc}")
    except HttpFailed as exc:
        return LinkDomainAge(
            status=ModuleStatus.UNAVAILABLE,
            domain=domain,
            reason=f"The public domain registry could not be read: {_FAILURE_REASONS.get(exc.kind, 'the request failed.')}",
        )
    if response.status != 200:
        reason = (
            "The public domain registry has no record it could share. Some domain endings don't publish one."
            if response.status == 404
            else f"The public domain registry answered with status {response.status}."
        )
        return LinkDomainAge(status=ModuleStatus.UNAVAILABLE, domain=domain, reason=reason)
    try:
        registered = _rdap_date(json.loads(response.body))
    except ValueError:
        registered = None
    if registered is None or registered > now:
        return LinkDomainAge(
            status=ModuleStatus.UNAVAILABLE, domain=domain, reason="The registry's answer gave no usable registration date."
        )
    return LinkDomainAge(
        status=ModuleStatus.COMPLETE,
        domain=domain,
        registered_on=registered.date().isoformat(),
        age_days=(now - registered).days,
        source="rdap.org",
    )


def _title_brand(title: str | None) -> str | None:
    if not title:
        return None
    lowered = title.casefold()
    return next((brand for brand in _BRANDS if re.search(rf"(?<![a-z]){brand}(?![a-z])", lowered)), None)


def _compare_official(brand: str, page: LinkPage, reader: _PageReader | None, budget: _Budget) -> LinkOfficialComparison:
    official = _BRANDS[brand][0]
    record = LinkOfficialComparison(status=ModuleStatus.UNAVAILABLE, brand=brand, official_domain=official)
    if page.status is not ModuleStatus.COMPLETE or reader is None:
        return record.model_copy(update={"reason": "The link's own page could not be read, so there was nothing to compare."})
    try:
        response = budget.get(f"https://{official}/", redirects=3)
    except (HttpBlocked, HttpFailed):
        return record.model_copy(update={"reason": f"The official site, {official}, could not be read for comparison."})
    if response.status != 200 or not _is_html(response):
        return record.model_copy(update={"reason": f"The official site, {official}, answered with status {response.status}."})
    theirs = _read_page(response)
    if theirs is None:
        return record.model_copy(update={"reason": f"The official site, {official}, could not be read for comparison."})
    their_title = _clean_title(theirs.title)
    return record.model_copy(
        update={
            "status": ModuleStatus.COMPLETE,
            "official_title": their_title,
            "title_similarity": _overlap(page.title or "", their_title or ""),
            "text_similarity": _overlap(" ".join(reader.text), " ".join(theirs.text)),
        }
    )


def _lookalike_signs(found: LinkLookalike, label: str) -> list[LinkSign]:
    if not found.brand:
        return []
    return [
        LinkSign(
            sign=f"lookalike_{found.strength}",
            strength=found.strength or "weak",
            why=(
                f"{label} {found.host} {found.how} {found.brand}. "
                f"The official domains we know of are {', '.join(found.official_domains)}."
            ),
        )
    ]


def _collect_signs(
    url: str,
    requested: LinkLookalike,
    final: LinkLookalike | None,
    redirects: LinkRedirects,
    domain: LinkDomainAge,
    page: LinkPage,
    official: LinkOfficialComparison,
    title_brand: str | None,
) -> list[LinkSign]:
    signs = _lookalike_signs(requested, "The link's domain")
    if final is not None:
        signs += _lookalike_signs(final, "The domain it leads to,")
    start = _host(url)
    end = redirects.final_host
    same_owner = bool(end) and _owned_brand(start) is not None and _owned_brand(start) == _owned_brand(end)
    if end and start not in SHORTENER_HOSTS and not same_owner and _registered_domain(start) != _registered_domain(end):
        signs.append(LinkSign(sign="redirects_elsewhere", strength="weak", why=f"The link redirects from {start} to {end}, a different domain."))
    if len(redirects.hops) > _MANY_HOPS:
        signs.append(LinkSign(sign="many_redirects", strength="weak", why=f"The link passes through {len(redirects.hops)} addresses before stopping."))
    if domain.age_days is not None and domain.age_days < _NEW_DOMAIN_DAYS:
        signs.append(LinkSign(sign="new_domain", strength="strong", why=f"{domain.domain} was registered only {domain.age_days} days ago."))
    elif domain.age_days is not None and domain.age_days < _YOUNG_DOMAIN_DAYS:
        signs.append(LinkSign(sign="young_domain", strength="weak", why=f"{domain.domain} was registered {domain.age_days} days ago."))
    asks = page.asks_for_login or page.asks_for_payment or page.asks_for_code
    final_url = redirects.final_url or url
    if asks and final_url.startswith("http://"):
        signs.append(LinkSign(sign="sensitive_form_without_https", strength="strong", why="The page asks for a password, code or card details without HTTPS."))
    if asks and title_brand:
        signs.append(
            LinkSign(
                sign="brand_title_on_form_page",
                strength="strong",
                why=f"The page's title names {title_brand} and asks for sign-in or payment details, but it isn't on a domain of {title_brand} we know of.",
            )
        )
    if asks and page.form_posts_to:
        signs.append(LinkSign(sign="form_posts_elsewhere", strength="weak", why=f"The page's form sends what is typed to a different domain: {', '.join(page.form_posts_to)}."))
    if official.status is ModuleStatus.COMPLETE and (official.title_similarity or 0) >= _SIMILAR_TITLE:
        signs.append(
            LinkSign(
                sign="copies_official_title",
                strength="strong",
                why=f"The page's title closely matches the title of {official.official_domain}, on a different domain.",
            )
        )
    return signs


def _assess(signs: list[LinkSign]) -> str:
    """Use the scam rules' scale: one weak sign alone is not treated as a warning."""
    if any(sign.strength == "strong" for sign in signs) or len(signs) >= 2:
        return WARNING_SIGNS
    return WEAK_ONLY if signs else NONE_FOUND


def investigate_link(
    url: str,
    *,
    offline_reason: str | None = None,
    request: Request = safe_request,
    now: datetime | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> LinkAnalysis:
    """Check a link. ``offline_reason`` says why no outside request may be made, and stops them all."""
    requested = find_lookalike(_host(url))
    threat_lists = LinkThreatLists(status=ModuleStatus.UNAVAILABLE, reason=THREAT_LIST_REASON)
    if offline_reason is not None:
        not_run = {"status": ModuleStatus.UNAVAILABLE, "reason": offline_reason}
        redirects = LinkRedirects(**not_run)
        domain = LinkDomainAge(**not_run)
        page = LinkPage(**not_run)
        final: LinkLookalike | None = None
        official = LinkOfficialComparison(
            brand=requested.brand,
            official_domain=_BRANDS[requested.brand][0] if requested.brand else None,
            **not_run,
        )
        title_brand = None
    else:
        budget = _Budget(request, clock)
        redirects, response, reader, current, unreadable = _follow(url, budget)
        page = _page_record(response, reader, redirects, current, unreadable)
        final_host = redirects.final_host or ""
        final = find_lookalike(final_host) if final_host and final_host != _host(url) else None
        checked_host = final_host or _host(url)
        domain = _domain_age(checked_host, budget, now or datetime.now(UTC))
        owner = _owned_brand(checked_host) if checked_host and not _is_ip(checked_host) else None
        named = _title_brand(page.title)
        title_brand = named if named and named != owner else None
        asks = page.asks_for_login or page.asks_for_payment or page.asks_for_code
        brand = (final.brand if final else None) or requested.brand or (title_brand if asks else None)
        if brand:
            official = _compare_official(brand, page, reader, budget)
        else:
            official = LinkOfficialComparison(
                status=ModuleStatus.NOT_APPLICABLE, reason="The link doesn't seem to imitate a name on our list, so nothing was compared."
            )
    signs = _collect_signs(url, requested, final, redirects, domain, page, official, title_brand)
    failed = offline_reason is None and ModuleStatus.UNAVAILABLE in (redirects.status, domain.status, page.status)
    return LinkAnalysis(
        live_failed=failed,
        assessment=_assess(signs),
        requested_host=_host(url),
        lookalike=final if final is not None and final.brand else requested,
        redirects=redirects,
        domain=domain,
        page=page,
        official=official,
        threat_lists=threat_lists,
        signs=signs,
        results_file=RESULTS_FILE,
        limitations=LIMITATIONS,
    )


def _part_check(check_id: str, label: str, status: ModuleStatus, result: str, reasoning: str) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "module": "url",
        "label": label,
        "status": status.value,
        "result": result,
        "reasoning": reasoning,
        "limitations": ["A sign is a reason to look closer, not proof."],
    }


def link_checks(link: LinkAnalysis) -> list[dict[str, Any]]:
    """Describe each part in the shared check format, including the parts that could not run."""
    look = link.lookalike
    hops = " -> ".join(hop.host for hop in link.redirects.hops)
    page = link.page
    asked = [
        word
        for word, flag in (("a password", page.asks_for_login), ("card or account details", page.asks_for_payment), ("a code", page.asks_for_code))
        if flag
    ]
    compared = link.official
    return [
        _part_check(
            "url.lookalike",
            "Lookalike domain",
            look.status,
            f"Imitates {look.brand}." if look.brand else ("Belongs to " + look.owned_by + "." if look.owned_by else "No imitation of a listed name."),
            f"{look.host} {look.how} {look.brand}." if look.brand else "Compared with a short list of well-known names.",
        ),
        _part_check(
            "url.redirects",
            "Redirects",
            link.redirects.status,
            f"Ends at {link.redirects.final_host}." if link.redirects.final_host else "Destination unknown.",
            link.redirects.reason or hops or "No request was made.",
        ),
        _part_check(
            "url.domain_age",
            "Domain age",
            link.domain.status,
            f"Registered {link.domain.registered_on}, {link.domain.age_days} days ago." if link.domain.age_days is not None else "Age unknown.",
            link.domain.reason or f"From {link.domain.source}, for {link.domain.domain}.",
        ),
        _part_check(
            "url.page",
            "Page content",
            page.status,
            f"Asks for {', '.join(asked)}." if asked else ("No sign-in or payment fields seen." if page.status is ModuleStatus.COMPLETE else "Page not read."),
            page.reason or (f"Title: {page.title}" if page.title else "The page has no title."),
        ),
        _part_check(
            "url.official_site",
            "Comparison with the official site",
            compared.status,
            f"Title overlap {compared.title_similarity}, text overlap {compared.text_similarity}, with {compared.official_domain}."
            if compared.status is ModuleStatus.COMPLETE
            else "Not compared.",
            compared.reason or "Word overlap between the two pages. Sites often share common words, so this is a rough signal.",
        ),
        _part_check("url.threat_lists", "Threat lists", link.threat_lists.status, "Not consulted.", link.threat_lists.reason or ""),
    ]
