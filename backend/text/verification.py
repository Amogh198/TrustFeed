"""Compare claims with public evidence and give each a cautious result.

The rules that keep this honest:

- Finding nothing gives ``unverified``. It never means false.
- No site is trusted by name. One domain, however well known, cannot settle a claim,
  so ``supported`` and ``contradicted`` need two independent domains that agree.
- A passage that seems to agree but lacks the claim's own figures or names only
  counts as partial, since it may be about something else.
- If the comparison models are missing, sources are still listed, but the claim
  stays ``unverified``, because nothing was actually compared.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from backend.text.claims import AnalyzedClaim, content_tokens, stem
from backend.text.evidence_sources import (
    Document,
    Provider,
    ProviderResult,
    default_providers,
)
from backend.text.verify_models import (
    Comparer,
    ComparisonUnavailable,
    Entailment,
    HuggingFaceComparer,
)

# Never log claims, queries or evidence: they come from what a user submitted.
logger = logging.getLogger(__name__)

SUPPORTED = "supported"
CONTRADICTED = "contradicted"
PARTIAL = "partially_supported"
UNVERIFIED = "unverified"

_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD = re.compile(r"[^\W\d_]+")
_DIGITS = re.compile(r"\d[\d,.]*\d|\d")
_REFUTING = re.compile(r"\b(?:false|fake|untrue|incorrect|debunked|hoax|fabricated|pants on fire|no evidence|baseless)\b", re.IGNORECASE)
_MIXED = re.compile(r"\b(?:misleading|partly|partially|mostly|half|mixed|missing context|out of context|needs context|exaggerat\w*|altered)\b", re.IGNORECASE)
_CONFIRMING = re.compile(r"\b(?:true|correct|accurate|confirmed)\b", re.IGNORECASE)
_TWO_PART_SUFFIXES = {"co.in", "co.uk", "com.au", "gov.in", "org.in", "net.in", "ac.in", "org.uk", "ac.uk", "gov.uk"}


@dataclass(frozen=True)
class VerifyConfig:
    max_claims: int = 5
    search_seconds: float = 20.0
    compare_seconds: float = 60.0
    # Passages kept per claim for the slower entailment model.
    top_passages: int = 6
    max_passages: int = 200
    min_passage_chars: int = 40
    # Below this a passage is about something else.
    min_similarity: float = 0.35
    # Contradiction is easy to trigger on loosely related text, so it needs more.
    min_contradiction_similarity: float = 0.5
    # A judgement needs a clear signal. Otherwise the passage is only related.
    strong_entailment: float = 0.7
    strong_contradiction: float = 0.8


@dataclass(frozen=True)
class SourceEvidence:
    provider: str
    title: str
    url: str
    domain: str
    date: str | None
    date_kind: str
    # supports, contradicts, partial, related or not_compared.
    stance: str
    explanation: str
    # A short quote, untrusted and to be shown as plain text only.
    snippet: str = ""
    similarity: float | None = None
    entailment: float | None = None
    contradiction: float | None = None
    rating: str | None = None


@dataclass(frozen=True)
class ClaimVerdict:
    claim_id: str
    verdict: str
    rationale: str
    sources: list[SourceEvidence] = field(default_factory=list)


@dataclass(frozen=True)
class VerificationReport:
    # complete: at least one search ran. unavailable: no search could. See ``reason``.
    status: str
    reason: str | None
    comparison_status: str
    comparison_reason: str | None
    providers: list[ProviderResult]
    verdicts: list[ClaimVerdict]
    skipped_claims: int
    limitations: list[str]


def build_query(claim: AnalyzedClaim) -> str:
    """Search words from the claim: its names, then its most specific other words."""
    names = [item.text for item in claim.named]
    used = {stem(word) for name in names for word in _WORD.findall(name)}
    words: list[str] = []
    match_text = claim.text
    wanted = content_tokens(claim)
    for word in _WORD.findall(match_text):
        token = stem(word)
        if token in wanted and token not in used and len(word) > 2:
            used.add(token)
            words.append(word)
    numbers = [number.text for number in claim.numbers[:1]]
    return " ".join([*names, *numbers, *words])[:200].strip()


def _passages(document: Document, config: VerifyConfig) -> list[str]:
    sentences = [part.strip() for part in _SENTENCE.split(document.text) if part.strip()]
    found = [sentence for sentence in sentences if len(sentence) >= config.min_passage_chars]
    return found[: config.max_passages]


def _registered_domain(domain: str) -> str:
    labels = domain.split(".")
    size = 3 if ".".join(labels[-2:]) in _TWO_PART_SUFFIXES else 2
    return ".".join(labels[-size:])


def _missing_specifics(claim: AnalyzedClaim, passage: str) -> list[str]:
    """The claim's figures, years and names that this passage does not state."""
    found_numbers = {item.replace(",", "") for item in _DIGITS.findall(passage)}
    lowered = passage.casefold()
    missing = [
        number.text
        for number in claim.numbers
        if not ({item.replace(",", "") for item in _DIGITS.findall(number.text)} & found_numbers)
    ]
    missing += [str(item.year) for item in claim.dates if item.year and str(item.year) not in lowered]
    missing += [item.text for item in claim.named if item.text.casefold() not in lowered]
    return missing


def _shares_subject(claim: AnalyzedClaim, passage: str) -> bool:
    if claim.named:
        lowered = passage.casefold()
        return any(item.text.casefold() in lowered for item in claim.named)
    words = {stem(word) for word in _WORD.findall(passage)}
    return len(content_tokens(claim) & words) >= 2


def _judge(
    claim: AnalyzedClaim, passage: str, score: Entailment, similarity: float, config: VerifyConfig
) -> tuple[str, str]:
    if score.entailment >= config.strong_entailment:
        missing = _missing_specifics(claim, passage)
        if missing:
            return "partial", f"This agrees in general, but does not state: {', '.join(missing)}."
        return "supports", "This passage states what the claim says."
    if (
        score.contradiction >= config.strong_contradiction
        and similarity >= config.min_contradiction_similarity
        and _shares_subject(claim, passage)
    ):
        return "contradicts", "This passage, on the same subject, says something the claim conflicts with."
    return "related", "This passage is on a related subject, but neither supports nor contradicts the claim."


def _judge_review(document: Document, score: Entailment, config: VerifyConfig) -> tuple[str, str]:
    """A fact-check rating only applies if the claim it reviewed says the same as this one."""
    if score.entailment < config.strong_entailment:
        return "related", f"A fact-checker rated a different claim \"{document.rating}\", so this does not settle it."
    rating = document.rating or ""
    if _MIXED.search(rating):
        return "partial", f"A fact-checker reviewed a matching claim and rated it \"{rating}\"."
    if _REFUTING.search(rating):
        return "contradicts", f"A fact-checker reviewed a matching claim and rated it \"{rating}\"."
    if _CONFIRMING.search(rating):
        return "supports", f"A fact-checker reviewed a matching claim and rated it \"{rating}\"."
    return "related", f"A fact-checker reviewed a matching claim, with the rating \"{rating}\", which could not be interpreted."


def _source(
    document: Document,
    stance: str,
    explanation: str,
    snippet: str = "",
    similarity: float | None = None,
    score: Entailment | None = None,
) -> SourceEvidence:
    return SourceEvidence(
        document.provider, document.title, document.url, document.domain, document.date, document.date_kind, stance,
        explanation, snippet[:280], similarity, score.entailment if score else None,
        score.contradiction if score else None, document.rating,
    )


_STANCE_ORDER = {"contradicts": 0, "supports": 1, "partial": 2, "related": 3, "not_compared": 4}


def _compare_claim(
    claim: AnalyzedClaim, documents: list[Document], comparer: Comparer, config: VerifyConfig
) -> list[SourceEvidence]:
    reviews = [document for document in documents if document.rating]
    candidates = [
        (document, passage)
        for document in documents
        if not document.rating
        for passage in _passages(document, config)
    ]
    sources: list[SourceEvidence] = []
    if reviews:
        scores = comparer.entail([(item.reviewed_claim or item.title, claim.text) for item in reviews])
        for review, score in zip(reviews, scores, strict=True):
            stance, explanation = _judge_review(review, score, config)
            sources.append(_source(review, stance, explanation, review.reviewed_claim or "", None, score))

    similarities = comparer.similarity(claim.text, [passage for _, passage in candidates])
    ranked = sorted(zip(candidates, similarities, strict=True), key=lambda item: item[1], reverse=True)
    close = [item for item in ranked if item[1] >= config.min_similarity][: config.top_passages]
    scores = comparer.entail([(passage, claim.text) for (_, passage), _ in close])
    # Keep the strongest result for each document, so one long page cannot count many times.
    best: dict[str, SourceEvidence] = {}
    for ((document, passage), similarity), score in zip(close, scores, strict=True):
        stance, explanation = _judge(claim, passage, score, similarity, config)
        current = best.get(document.url)
        if current is None or _STANCE_ORDER[stance] < _STANCE_ORDER[current.stance]:
            best[document.url] = _source(document, stance, explanation, passage, similarity, score)
    sources.extend(best.values())
    return sorted(sources, key=lambda item: _STANCE_ORDER[item.stance])


def decide(sources: Sequence[SourceEvidence]) -> tuple[str, str]:
    """Turn sources into one result. Independent domains count, and names do not."""
    def domains(stance: str) -> set[str]:
        return {_registered_domain(item.domain) for item in sources if item.stance == stance}

    supporting, contradicting, partial = domains("supports"), domains("contradicts"), domains("partial")
    if supporting and contradicting:
        return PARTIAL, (
            f"Sources disagree. {_listed(supporting)} support this and {_listed(contradicting)} contradict it. "
            "Read both before relying on it."
        )
    if len(contradicting) >= 2:
        return CONTRADICTED, f"Independent sources contradict this: {_listed(contradicting)}."
    if len(supporting) >= 2:
        return SUPPORTED, f"Independent sources support this: {_listed(supporting)}."
    if contradicting:
        return PARTIAL, (
            f"Only one source contradicts this ({_listed(contradicting)}), which is not enough to settle it. "
            "A well-known site can still be wrong."
        )
    if supporting:
        return PARTIAL, (
            f"Only one source supports this ({_listed(supporting)}), which is not enough to settle it. "
            "A well-known site can still be wrong."
        )
    if partial:
        return PARTIAL, f"{_listed(partial)} support part of this, but not every detail."
    if sources:
        return UNVERIFIED, "Related sources were found, but none clearly supports or contradicts this. That does not mean it is false."
    return UNVERIFIED, "No relevant source was found. That does not mean it is false."


def _listed(domains: set[str]) -> str:
    return ", ".join(sorted(domains))


def _search(claim: AnalyzedClaim, providers: Sequence[Provider], config: VerifyConfig) -> list[ProviderResult]:
    query = build_query(claim)
    if not query:
        return [ProviderResult(provider.name, "complete") for provider in providers]
    deadline = time.monotonic() + config.search_seconds
    results: list[ProviderResult] = []
    for provider in providers:
        try:
            results.append(provider.search(query, deadline))
        except Exception as error:  # noqa: BLE001 - One failed service must not lose the others.
            logger.warning("Evidence provider failed: %s", type(error).__name__)
            results.append(ProviderResult(provider.name, "unavailable", "The service failed unexpectedly."))
    return results


def _merge_providers(rounds: list[list[ProviderResult]]) -> list[ProviderResult]:
    """One row per service. It is complete if any of its searches worked."""
    merged: dict[str, ProviderResult] = {}
    for results in rounds:
        for result in results:
            current = merged.get(result.name)
            if current is None:
                merged[result.name] = result
                continue
            status = "complete" if "complete" in (current.status, result.status) else "unavailable"
            merged[result.name] = ProviderResult(
                result.name, status, None if status == "complete" else result.reason,
                [*current.documents, *result.documents],
            )
    return list(merged.values())


class _TimeLimit(Exception):
    pass


def _within_limit(work: Callable[[], list[list[SourceEvidence]]], seconds: float) -> list[list[SourceEvidence]]:
    """Run model work in a thread, because Python cannot interrupt a model call."""
    box: dict[str, object] = {}
    finished = threading.Event()

    def run() -> None:
        try:
            box["value"] = work()
        except Exception as exc:  # noqa: BLE001 - Passed to the caller below.
            box["error"] = exc
        finally:
            finished.set()

    threading.Thread(target=run, daemon=True, name="text-verify").start()
    if not finished.wait(seconds):
        raise _TimeLimit
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box["value"]  # type: ignore[return-value]


def _not_compared(documents: list[Document], reason: str) -> list[SourceEvidence]:
    return [_source(document, "not_compared", f"This was found but not compared with the claim. {reason}") for document in documents]


def verify_claims(
    claims: Sequence[AnalyzedClaim],
    *,
    providers: Sequence[Provider] | None = None,
    comparer: Comparer | None = None,
    config: VerifyConfig | None = None,
) -> VerificationReport:
    """Only call this when the user allowed outside search. Problems are reported, not raised."""
    settings = config or _config_from_env()
    if os.getenv("PROVENANCE_REPLAY_PATH"):
        reason = "Replay mode stays offline, so no public source was searched."
        return VerificationReport("unavailable", reason, "not_applicable", None, [], [], 0, [reason])

    services = list(providers) if providers is not None else default_providers()
    models = comparer or _default_comparer()
    checkable = [claim for claim in claims if claim.checkable]
    chosen = checkable[: settings.max_claims]
    skipped = len(checkable) - len(chosen)

    rounds = [_search(claim, services, settings) for claim in chosen]
    documents_by_claim = [_unique_documents(results) for results in rounds]
    comparison_reason = models.is_ready()
    # With no evidence there was nothing to compare, which is not the same as having compared it.
    comparison_status = "unavailable" if comparison_reason else "not_applicable"
    compared: list[list[SourceEvidence]] | None = None
    if not comparison_reason and any(documents_by_claim):
        comparison_status = "complete"
        try:
            compared = _within_limit(
                lambda: [
                    _compare_claim(claim, documents, models, settings) if documents else []
                    for claim, documents in zip(chosen, documents_by_claim, strict=True)
                ],
                settings.compare_seconds,
            )
        except _TimeLimit:
            comparison_status = "unavailable"
            comparison_reason = f"The comparison did not finish within {settings.compare_seconds:g} seconds."
        except ComparisonUnavailable as error:
            comparison_status = "unavailable"
            comparison_reason = str(error)
        except Exception as error:  # noqa: BLE001 - A model failure must not lose the case.
            logger.warning("Claim comparison failed: %s", type(error).__name__)
            comparison_status = "unavailable"
            comparison_reason = "The comparison models failed while reading this evidence."

    verdicts: list[ClaimVerdict] = []
    for index, claim in enumerate(chosen):
        if compared is not None:
            sources = compared[index]
            verdict, rationale = decide(sources)
        else:
            sources = _not_compared(documents_by_claim[index], comparison_reason or "")
            verdict = UNVERIFIED
            rationale = (
                f"Sources were found, but could not be compared with this claim. {comparison_reason}"
                if sources
                else "No relevant source was found. That does not mean it is false."
            )
        verdicts.append(ClaimVerdict(claim.id, verdict, rationale, sources))

    merged = _merge_providers(rounds)
    any_search = any(result.status == "complete" for result in merged)
    limitations = [
        "A result compares this claim with what these searches found. It is a signal, not proof.",
        "Finding nothing never means a claim is false, and a well-known site can still be wrong.",
        "Sources that repeat each other can look independent. Only the domain name is compared.",
        "Searches and passages are in English, so evidence in other languages can be missed.",
    ]
    limitations += [f"{result.name}: {result.reason}" for result in merged if result.status != "complete" and result.reason]
    if skipped:
        limitations.append(f"Only the first {settings.max_claims} checkable claims were searched. {skipped} more were not.")
    if comparison_reason:
        limitations.append(f"Sources were not compared with the claims. {comparison_reason}")
    return VerificationReport(
        "complete" if any_search else "unavailable",
        None if any_search else "No public source could be searched.",
        comparison_status,
        comparison_reason,
        merged,
        verdicts,
        skipped,
        limitations,
    )


def _unique_documents(results: list[ProviderResult]) -> list[Document]:
    seen: set[str] = set()
    documents: list[Document] = []
    for result in results:
        for document in result.documents:
            if document.url not in seen:
                seen.add(document.url)
                documents.append(document)
    return documents


def _config_from_env() -> VerifyConfig:
    try:
        seconds = float(os.getenv("TEXT_COMPARE_TIMEOUT_SECONDS", ""))
    except ValueError:
        return VerifyConfig()
    return VerifyConfig(compare_seconds=seconds) if seconds > 0 else VerifyConfig()


_comparer: HuggingFaceComparer | None = None


def _default_comparer() -> HuggingFaceComparer:
    global _comparer
    if _comparer is None:
        _comparer = HuggingFaceComparer()
    return _comparer
