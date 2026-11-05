"""Finds where an image appeared before. One failed step never stops the others.

A search reports where an image was found and when. It cannot show who made it, or
that a page was first. Nothing leaves the server unless ``search_web`` is true.
"""

from __future__ import annotations

import io
import logging
import threading
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from backend.media.config import MediaConfig
from backend.media.errors import HashIndexUnavailable, MediaInputError
from backend.media.metadata import inspect_input, read_image
from backend.media.models import MediaType
from backend.media.phash import JsonHashIndex, compute_phash, hamming_distance
from backend.provenance.cache import ResultsCache
from backend.provenance.classify import classify_platform, clean_text, clean_url, dedupe_key, domain_of
from backend.provenance.config import ProvenanceConfig
from backend.provenance.dates import PageDate, PageFacts, parse_date, read_page_facts
from backend.provenance.models import (
    Appearance,
    DateSource,
    EarliestFound,
    MatchType,
    Platform,
    ProvenanceReport,
    ProviderRun,
    Status,
)
from backend.provenance.providers import Candidate, Provider, ProviderFailure, Upload, configured_providers
from backend.provenance.replay import replay_report
from backend.provenance.safe_http import HttpBlocked, HttpFailed, RequestFunction, safe_request

# URLs and file names are never logged: they can reveal what a user submitted.
logger = logging.getLogger(__name__)

SEARCH_COVERAGE = (
    "A search only covers pages these services have indexed. Private groups, deleted pages and much of social media "
    "are not covered."
)
NOTHING_FOUND = "Finding nothing does not show that an image is new or genuine."
SIMILARITY_ONLY = (
    "A match shows that a page holds a similar picture. It does not show who made the picture or whether a claim "
    "about it is true."
)
DATES_CAVEAT = (
    "Dates come from the pages and crawlers named on each result. A page can state a date falsely, and its date can "
    "be older than an image added to it later."
)
_CRAWL_EVIDENCE = (
    "TinEye's crawl date: when its crawler saw this image on the page, which is not when the page published it."
)
_MATCH_RANK = {MatchType.EXACT: 0, MatchType.PARTIAL: 1, MatchType.SIMILAR: 2}


class _SitePacing:
    """Spaces out requests to each site, so checking results never hammers one of them."""

    def __init__(self, config: ProvenanceConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        self._next_at: dict[str, float] = {}
        self._delays: dict[str, float] = {}

    def set_delay(self, host: str, seconds: float) -> None:
        with self._lock:
            self._delays[host] = min(max(seconds, self._config.site_delay_s), self._config.max_site_delay_s)

    def wait(self, url: str, deadline: float | None) -> None:
        host = urlsplit(url).netloc
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next_at.get(host, now))
            self._next_at[host] = start + self._delays.get(host, self._config.site_delay_s)
        pause = start - now
        if pause <= 0:
            return
        if deadline is not None and start > deadline:
            raise HttpFailed("timeout")
        time.sleep(pause)

    def wrap(self, http: RequestFunction) -> RequestFunction:
        def paced(url: str, **options):
            self.wait(url, options.get("deadline"))
            return http(url, **options)

        return paced


@dataclass
class _CheckResult:
    facts: PageFacts = field(default_factory=PageFacts)
    page_status: str = "not_checked"
    distance: int | None = None


class _Robots:
    """Answers robots.txt rules, fetching each site's file once per search."""

    def __init__(
        self, http: RequestFunction, config: ProvenanceConfig, deadline: float, pacing: _SitePacing | None = None
    ) -> None:
        self._http = http
        self._config = config
        self._deadline = deadline
        self._pacing = pacing
        self._lock = threading.Lock()
        self._host_locks: dict[str, threading.Lock] = {}
        self._rules: dict[str, RobotFileParser | None] = {}

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = urlunsplit((parts.scheme, parts.netloc, "", "", ""))
        with self._lock:
            host_lock = self._host_locks.setdefault(origin, threading.Lock())
        with host_lock:
            if origin not in self._rules:
                self._rules[origin] = self._load(origin)
        rules = self._rules[origin]
        return bool(rules and rules.can_fetch(self._config.user_agent, url))

    def _load(self, origin: str) -> RobotFileParser | None:
        """Return the rules. None means fetching is not allowed for this site."""
        rules = RobotFileParser()
        try:
            response = self._http(
                f"{origin}/robots.txt",
                headers={"User-Agent": self._config.user_agent},
                timeout_s=self._config.request_timeout_s,
                max_bytes=self._config.max_robots_bytes,
                deadline=self._deadline,
                max_redirects=self._config.max_redirects,
            )
        except (HttpBlocked, HttpFailed):
            return None
        if 400 <= response.status < 500:
            rules.parse([])  # No robots.txt means no restrictions.
            return rules
        if response.status != 200:
            return None  # An unreachable robots.txt is treated as "keep out".
        rules.parse(response.body.decode("utf-8", "replace").splitlines())
        delay = rules.crawl_delay(self._config.user_agent)
        if delay and self._pacing is not None:
            self._pacing.set_delay(urlsplit(origin).netloc, float(delay))
        return rules


def _candidate_phash(data: bytes, config: ProvenanceConfig) -> str | None:
    """Hash a downloaded image. Its bytes are untrusted, so any failure just means no hash."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP", "GIF"}:
                return None
            width, height = image.size
            if width * height > config.max_candidate_image_pixels:
                return None
            return compute_phash(image.convert("RGB"))
    except Exception:  # Pillow raises many types on hostile files.
        return None


def _check_candidate(
    candidate: Candidate,
    upload_phash: str | None,
    http: RequestFunction,
    robots: _Robots,
    config: ProvenanceConfig,
    deadline: float,
) -> _CheckResult:
    result = _CheckResult()
    headers = {"User-Agent": config.user_agent}

    if candidate.page_url:
        if not robots.allowed(candidate.page_url):
            result.page_status = "robots"
        else:
            try:
                response = http(
                    candidate.page_url,
                    headers=headers,
                    timeout_s=config.request_timeout_s,
                    max_bytes=config.max_page_bytes,
                    deadline=deadline,
                    max_redirects=config.max_redirects,
                )
            except (HttpBlocked, HttpFailed):
                result.page_status = "failed"
            else:
                if response.status == 200:
                    result.facts = read_page_facts(response.headers, response.body)
                    result.page_status = "checked"
                else:
                    result.page_status = "failed"

    if candidate.image_url and upload_phash and robots.allowed(candidate.image_url):
        try:
            response = http(
                candidate.image_url,
                headers=headers,
                timeout_s=config.request_timeout_s,
                max_bytes=config.max_candidate_image_bytes,
                deadline=deadline,
                max_redirects=config.max_redirects,
            )
        except (HttpBlocked, HttpFailed):
            pass
        else:
            if response.status == 200:
                phash = _candidate_phash(response.body, config)
                if phash:
                    result.distance = hamming_distance(upload_phash, phash)
    return result


def _merge(candidates: Sequence[Candidate], limit: int) -> list[Candidate]:
    """Keep one result per page, with the strongest match and the earliest crawl date."""
    merged: dict[str, Candidate] = {}
    for candidate in sorted(candidates, key=lambda c: _MATCH_RANK[c.match_type]):
        url = candidate.page_url or candidate.image_url
        if not url:
            continue
        key = dedupe_key(url)
        existing = merged.get(key)
        if existing is None:
            merged[key] = candidate
            continue
        existing.page_title = existing.page_title or candidate.page_title
        existing.image_url = existing.image_url or candidate.image_url
        existing.provider_date_text = existing.provider_date_text or candidate.provider_date_text
        if candidate.crawl_date and (not existing.crawl_date or candidate.crawl_date < existing.crawl_date):
            existing.crawl_date = candidate.crawl_date
        if existing.provider != candidate.provider and candidate.provider not in existing.provider:
            existing.provider = f"{existing.provider}, {candidate.provider}"
    ordered = sorted(
        merged.values(),
        key=lambda c: (_MATCH_RANK[c.match_type], c.page_url is None),
    )
    return ordered[:limit]


def _final_match_type(candidate: Candidate, distance: int | None, config: ProvenanceConfig) -> MatchType:
    if distance is None:
        return candidate.match_type
    if candidate.decide_type_by_phash:
        return MatchType.EXACT if distance <= config.same_image_distance else MatchType.PARTIAL
    if candidate.match_type is MatchType.EXACT and distance > config.related_image_distance:
        return MatchType.SIMILAR
    return candidate.match_type


def _choose_date(
    candidate: Candidate, check: _CheckResult, platform: Platform
) -> tuple[datetime | None, DateSource, str]:
    page: PageDate | None = check.facts.date
    crawl = candidate.crawl_date
    # A crawler cannot see an image before it exists, so an earlier crawl date wins.
    if page and (not crawl or page.observed_at <= crawl):
        source = DateSource.SOCIAL_POST if platform is Platform.SOCIAL else DateSource.PAGE_METADATA
        return page.observed_at, source, page.evidence
    if crawl:
        return crawl, DateSource.CRAWL_DATE, _CRAWL_EVIDENCE
    if candidate.provider_date_text:
        return None, DateSource.NONE, (
            f'The search result showed "{candidate.provider_date_text}", which is too vague to use as a date.'
        )
    if check.page_status == "robots":
        return None, DateSource.NONE, "The site's robots.txt does not allow this page to be read, so no date was read."
    if check.page_status == "failed":
        return None, DateSource.NONE, "The page could not be read, so no date was found."
    if check.page_status == "checked":
        return None, DateSource.NONE, "The page states no publication date."
    return None, DateSource.NONE, "Only an image URL was returned, with no page to read a date from."


def _to_appearance(
    candidate: Candidate, check: _CheckResult, config: ProvenanceConfig
) -> Appearance:
    domain = domain_of(candidate.page_url or candidate.image_url)
    platform = classify_platform(domain, is_news_article=check.facts.is_news_article)
    observed_at, source, evidence = _choose_date(candidate, check, platform)
    return Appearance(
        id="",
        page_url=candidate.page_url,
        page_title=candidate.page_title or check.facts.title,
        domain=domain,
        platform=platform,
        image_url=candidate.image_url,
        match_type=_final_match_type(candidate, check.distance, config),
        phash_distance=check.distance,
        observed_at=observed_at,
        date_source=source,
        date_evidence=evidence,
        provider=candidate.provider,
    )


def _local_appearances(
    phash: str | None, media_config: MediaConfig
) -> tuple[ProviderRun, list[Appearance]]:
    name = "local_index"
    if media_config.phash_index_path is None:
        return ProviderRun(name=name, status=Status.NOT_APPLICABLE, limitation="No reference list is configured."), []
    try:
        index = JsonHashIndex.load(media_config.phash_index_path)
    except HashIndexUnavailable as exc:
        return ProviderRun(name=name, status=Status.UNAVAILABLE, limitation=str(exc)), []
    if phash is None:
        return ProviderRun(name=name, status=Status.UNAVAILABLE, limitation="This file has no image hash."), []

    appearances = []
    for match in index.lookup(phash, media_config.phash_max_distance):
        first_seen = clean_text(match.first_seen, limit=40)
        parsed = parse_date(first_seen)
        page_url = clean_url(match.source)
        if parsed:
            evidence = f"The team's reference list says first seen {first_seen}."
        elif first_seen:
            evidence = f'The team\'s reference list says first seen "{first_seen}", which is not a full date.'
        else:
            evidence = "The team's reference list gives no date."
        appearances.append(
            Appearance(
                id="",
                page_url=page_url,
                page_title=clean_text(match.label),
                domain=domain_of(page_url),
                platform=classify_platform(domain_of(page_url)),
                match_type=MatchType.EXACT,
                phash_distance=match.distance,
                observed_at=parsed[0] if parsed else None,
                date_source=DateSource.REFERENCE_INDEX if parsed else DateSource.NONE,
                date_evidence=evidence,
                provider=name,
            )
        )
    return ProviderRun(name=name, status=Status.COMPLETE, result_count=len(appearances)), appearances


def _earliest(appearances: Sequence[Appearance], config: ProvenanceConfig) -> EarliestFound | None:
    """Choose only from dated results, leaving out similar pictures not shown to be related."""

    def usable(item: Appearance) -> bool:
        if item.observed_at is None:
            return False
        if item.match_type is MatchType.SIMILAR:
            return item.phash_distance is not None and item.phash_distance <= config.same_image_distance
        return True

    dated = [item for item in appearances if usable(item)]
    if not dated:
        return None
    first = min(dated, key=lambda item: item.observed_at)
    return EarliestFound(appearance_id=first.id, observed_at=first.observed_at, date_source=first.date_source)


def _run_providers(
    providers: Sequence[Provider],
    upload: Upload,
    http: RequestFunction,
    config: ProvenanceConfig,
    media_sha256: str | None = None,
) -> tuple[list[ProviderRun], list[Candidate]]:
    runs: list[ProviderRun] = []
    found: list[Candidate] = []
    cache = ResultsCache(config.cache_dir, config.cache_days) if config.cache_dir and media_sha256 else None
    for provider in providers:
        cache_key = getattr(provider, "cache_key", provider.name)
        saved = cache.get(media_sha256, cache_key) if cache else None
        if saved is not None:
            candidates, saved_at = saved
            note = f"{provider.name}: saved results from {saved_at:%Y-%m-%d} were reused, so no search was spent."
            runs.append(ProviderRun(name=provider.name, status=Status.COMPLETE, result_count=len(candidates), limitation=note))
            found.extend(candidates)
            continue
        try:
            candidates = provider.search(upload, http, config)
        except ProviderFailure as exc:
            runs.append(ProviderRun(name=provider.name, status=Status.UNAVAILABLE, limitation=str(exc)))
        except Exception as exc:
            logger.warning("Provenance provider failed: %s", type(exc).__name__)
            runs.append(
                ProviderRun(
                    name=provider.name,
                    status=Status.UNAVAILABLE,
                    limitation=f"{provider.name} failed unexpectedly.",
                )
            )
        else:
            notes = getattr(provider, "notes", [])
            runs.append(
                ProviderRun(
                    name=provider.name,
                    status=Status.COMPLETE,
                    result_count=len(candidates),
                    limitation=" ".join(notes) or None,
                )
            )
            found.extend(candidates)
            # A partial answer isn't saved, so the next search can complete it.
            if cache and not notes:
                cache.put(media_sha256, cache_key, candidates)
    return runs, found


def _check_all(
    candidates: Sequence[Candidate],
    upload_phash: str | None,
    http: RequestFunction,
    config: ProvenanceConfig,
) -> tuple[list[Appearance], list[str]]:
    if not candidates:
        return [], []
    deadline = time.monotonic() + config.check_budget_s
    pacing = _SitePacing(config)
    http = pacing.wrap(http)
    robots = _Robots(http, config, deadline, pacing)
    pool = ThreadPoolExecutor(max_workers=config.check_workers)
    futures = {
        pool.submit(_check_candidate, candidate, upload_phash, http, robots, config, deadline): candidate
        for candidate in candidates
    }
    done, pending = wait(futures, timeout=config.check_budget_s + 1)
    pool.shutdown(wait=False, cancel_futures=True)

    appearances = []
    for future, candidate in futures.items():
        check = _CheckResult()
        if future in done:
            try:
                check = future.result()
            except Exception as exc:
                logger.warning("Provenance page check failed: %s", type(exc).__name__)
                check = _CheckResult(page_status="failed")
        appearances.append(_to_appearance(candidate, check, config))

    notes = []
    if pending:
        notes.append(f"{len(pending)} results were not checked before the time limit, so they may lack dates.")
    if any("robots.txt" in (item.date_evidence or "") for item in appearances):
        notes.append("Some pages were not read because their robots.txt does not allow it.")
    unverified = sum(item.phash_distance is None and item.image_url is not None for item in appearances)
    if unverified:
        notes.append(f"{unverified} matching images could not be downloaded to confirm the match.")
    return appearances, notes


def _finalize(report: ProvenanceReport, appearances: list[Appearance], config: ProvenanceConfig) -> ProvenanceReport:
    far_future = datetime.max.replace(tzinfo=timezone.utc)
    appearances.sort(key=lambda item: (item.observed_at or far_future, _MATCH_RANK[item.match_type]))
    for number, item in enumerate(appearances, start=1):
        item.id = f"a{number}"
    report.appearances = appearances
    report.earliest_found = _earliest(appearances, config)
    return report


def _unavailable(reason: str, **fields) -> ProvenanceReport:
    return ProvenanceReport(status=Status.UNAVAILABLE, limitations=[reason], **fields)


def _investigate(
    path: Path,
    search_web: bool,
    config: ProvenanceConfig,
    providers: Sequence[Provider] | None,
    http: RequestFunction,
) -> ProvenanceReport:
    media_config = MediaConfig.from_env()
    try:
        info = inspect_input(path, media_config)
    except MediaInputError as exc:
        return _unavailable(exc.message)

    if config.replay_path is not None:
        return replay_report(config.replay_path, info.sha256)

    if info.media_type is not MediaType.IMAGE:
        return _unavailable(
            "Source search currently supports images only. No search was run for this video.",
            media_sha256=info.sha256,
        )
    try:
        image, _, _ = read_image(path, media_config)
    except MediaInputError as exc:
        return _unavailable(exc.message, media_sha256=info.sha256)
    except ImportError:
        return _unavailable("Pillow is not installed, so the image could not be read.", media_sha256=info.sha256)

    try:
        phash = compute_phash(image)
    except Exception as exc:
        logger.warning("Provenance pHash failed: %s", type(exc).__name__)
        phash = None

    local_run, local_items = _local_appearances(phash, media_config)
    runs = [local_run]
    appearances = list(local_items)
    limitations: list[str] = []
    searched_at = None

    if search_web:
        active = list(providers) if providers is not None else configured_providers(config)
        if not active:
            limitations.append("No web search provider has a key configured, so no web search was run.")
        else:
            searched_at = datetime.now(timezone.utc)
            provider_runs, candidates = _run_providers(active, Upload(image), http, config, info.sha256)
            runs.extend(provider_runs)
            merged = _merge(candidates, config.max_candidates)
            if len(candidates) > len(merged) and len(merged) == config.max_candidates:
                limitations.append(f"Only the top {config.max_candidates} results were checked.")
            checked, notes = _check_all(merged, phash, http, config)
            appearances.extend(checked)
            limitations.extend(notes)
    else:
        limitations.append("Web search was not requested, so the image was not sent to any outside service.")

    completed = [run for run in runs if run.status is Status.COMPLETE]
    if completed:
        status = Status.COMPLETE
    elif search_web:
        status = Status.UNAVAILABLE
    else:
        status = Status.NOT_APPLICABLE

    if status is Status.COMPLETE and searched_at is not None:
        limitations.extend([SEARCH_COVERAGE, DATES_CAVEAT, SIMILARITY_ONLY])
    if status is Status.COMPLETE and not appearances:
        limitations.append(NOTHING_FOUND)
    limitations.extend(run.limitation for run in provider_failures(runs))
    limitations.extend(run.limitation for run in runs if run.status is Status.COMPLETE and run.limitation)

    report = ProvenanceReport(
        status=status,
        searched_at=searched_at,
        media_sha256=info.sha256,
        phash=phash,
        providers=runs,
        limitations=list(dict.fromkeys(limitations)),
    )
    return _finalize(report, appearances, config)


def provider_failures(runs: Sequence[ProviderRun]) -> list[ProviderRun]:
    return [run for run in runs if run.status is Status.UNAVAILABLE and run.limitation]


def investigate_provenance(
    path: str | Path,
    *,
    search_web: bool,
    config: ProvenanceConfig | None = None,
    providers: Sequence[Provider] | None = None,
    http: RequestFunction = safe_request,
) -> ProvenanceReport:
    """Report where an image was found. Expected failures are reported, never raised.

    The image leaves the server only when ``search_web`` is true and a provider is set.
    """
    config = config or ProvenanceConfig.from_env()
    try:
        return _investigate(Path(path), search_web, config, providers, http)
    except Exception as exc:
        logger.warning("Provenance search failed: %s", type(exc).__name__)
        return _unavailable("The source search failed unexpectedly, so no result is available.")
