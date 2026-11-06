"""Unified risk: separate components, each with its evidence, and only measured signals scored.

What counts: the media detector, the scam rules and the link address check, as each has a
results file. Language rules, claim verdicts, inconsistencies, cross-modal differences, live
link signs and spread have none, so they are shown but never scored. If any of them raises
concern while the score stays low, the level is Inconclusive rather than Low.

This is a triage signal and never a verdict. No check can show content is genuine, so the
trust score stays at or below 50.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping

from datetime import date

from backend.api.app.models import (
    ClaimAnalysis,
    CrossModalAnalysis,
    LinkAnalysis,
    ModuleResult,
    ModuleStatus,
    RiskComponent,
    RiskLevel,
    ScamAnalysis,
    UnifiedRisk,
)
from backend.text.scams import NONE_FOUND, WARNING_SIGNS

DEFAULT_WEIGHTS = {"media": 1.0, "scam": 1.0, "link": 1.0}
MEDIA_RESULTS = "data/eval/commons_2026-11-05.json"
SCAM_RESULTS = "backend/text/evaluation/results/scam_eval_test.json"
LINK_RESULTS = "backend/text/evaluation/results/link_eval_test.json"
NEUTRAL_TRUST = 50
_ESTABLISHED_DAYS = 5 * 365
_YEAR_DAYS = 365
_STRONG = 0.7
_WEAK = 0.3
# One uncalibrated model never reaches critical alone.
_MEDIA_CAP = 0.75
_LISTED = 0.95
_RULES_CAP = 0.55
_ELEVATED = 0.75
_THRESHOLDS = ((0.8, RiskLevel.CRITICAL), (0.6, RiskLevel.HIGH), (0.3, RiskLevel.MODERATE))
_TRUST_CAPS = {RiskLevel.MODERATE: 40, RiskLevel.HIGH: 25, RiskLevel.CRITICAL: 25}
# How far each model's score lowers trust. The phishing model on text flags many normal posts, so it counts least.
_MODEL_WEIGHTS = {"link": 0.25, "text": 0.2, "media": 0.5}
# On held-out domains this line caught 61.8% of phishing hosts and flagged 0.77% of ordinary ones.
LINK_MODEL_LINE = 0.8
_NOT_MEASURED = "Not scored, because this has not been measured on labelled data."


# The panel detectors that separated fakes from real images in backend/media/README.md's benchmark.
VOTING_DETECTORS = ("nonescape/nonescape-mini-v0", "Ateeqq/ai-vs-human-image-detector", "haywoodsloan/ai-image-detector-deploy")
VOTE_LINE = 0.75
# DALL-E 2's release. Older AI image methods existed, so this is strong evidence, not proof.
BEFORE_IMAGE_GENERATORS = date(2022, 4, 1).isoformat()
_OLD_IMAGE_FACTOR = 0.2
_WIDE_IMAGE_FACTOR = 0.7
_WIDE_DOMAINS = 5


def panel_vote(detectors: list[dict]) -> dict | None:
    """Count how many useful detectors flag the media. Fewer than two results is no vote."""
    scores = {d["model_id"]: d["score"] for d in detectors if d.get("model_id") in VOTING_DETECTORS and d.get("score") is not None}
    if len(scores) < 2:
        return None
    return {"flagged": sum(score >= VOTE_LINE for score in scores.values()), "total": len(scores), "mean": sum(scores.values()) / len(scores)}


def load_weights(raw: str | None = None) -> dict[str, float]:
    """Read ``RISK_WEIGHTS``, set by whoever runs the server. Anything invalid keeps the default."""
    raw = os.getenv("RISK_WEIGHTS", "") if raw is None else raw
    weights = dict(DEFAULT_WEIGHTS)
    try:
        given = json.loads(raw) if raw else {}
    except ValueError:
        return weights
    if isinstance(given, dict):
        for name, value in given.items():
            if name in weights and isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1:
                weights[name] = float(value)
    return weights


def _level(score: float) -> RiskLevel:
    return next((level for floor, level in _THRESHOLDS if score >= floor), RiskLevel.LOW)


def _media(module: ModuleResult | None, level: RiskLevel | None, weights: Mapping[str, float]) -> RiskComponent:
    base = {"name": "media", "label": "Media detector", "weight": weights["media"], "evidence": list(module.evidence) if module else [], "results_file": MEDIA_RESULTS}
    if module is None or module.status is ModuleStatus.NOT_APPLICABLE:
        return RiskComponent(status=ModuleStatus.NOT_APPLICABLE, counted=False, note="No media was submitted.", **base)
    if module.status is not ModuleStatus.COMPLETE or module.score is None:
        note = module.limitations[0] if module.limitations else "The media check gave no result."
        return RiskComponent(status=ModuleStatus.UNAVAILABLE, counted=False, blocks_low=True, note=note, **base)
    # The media check's own assessment decides, as a video whose frames disagree can score high and still be unclear.
    if level not in (RiskLevel.MODERATE, RiskLevel.HIGH):
        # In the benchmark it scored most fakes low, so a quiet detector says nothing either way.
        return RiskComponent(
            status=ModuleStatus.COMPLETE,
            counted=False,
            blocks_low=True,
            score=module.score,
            note=f"Scored {module.score:.4f}, with no strong signal. Detectors miss many fakes, so this does not show the media is real.",
            **base,
        )
    score = min(_MEDIA_CAP, module.score) if level is RiskLevel.HIGH else max(_WEAK, min(module.score, _ELEVATED - 0.01))
    return RiskComponent(status=ModuleStatus.COMPLETE, counted=True, score=score, **base)


def _with_vote(component: RiskComponent, vote: dict | None) -> RiskComponent:
    if vote:
        extra = f"{vote['source_note']} " if vote.get("source_note") else ""
        component.note = f"{extra}{vote['flagged']} of {vote['total']} detectors flagged this, average score {vote['mean']:.3f}. {component.note or ''}".strip()
    return component


def _scam(analysis: ScamAnalysis | None, weights: Mapping[str, float]) -> RiskComponent:
    base = {"name": "scam", "label": "Scam warning signs", "weight": weights["scam"], "results_file": SCAM_RESULTS}
    if analysis is None:
        return RiskComponent(status=ModuleStatus.NOT_APPLICABLE, counted=False, note="No text was submitted.", **base)
    score = _STRONG if analysis.assessment == WARNING_SIGNS else 0.0 if analysis.assessment == NONE_FOUND else _WEAK
    return RiskComponent(
        status=ModuleStatus.COMPLETE, counted=True, score=score, evidence=[f"{item.why} Found: {item.quote!r}" for item in analysis.signs], **base
    )


def _link(analysis: LinkAnalysis | None, url: ModuleResult | None, weights: Mapping[str, float]) -> RiskComponent:
    base = {"name": "link", "label": "Link checks", "weight": weights["link"], "results_file": LINK_RESULTS}
    if analysis is None:
        return RiskComponent(status=ModuleStatus.NOT_APPLICABLE, counted=False, note="No link was submitted.", **base)
    names = {item.sign for item in analysis.signs}
    strong = any(item.strength == "strong" for item in analysis.signs)
    score = _LISTED if "threat_listed" in names else _STRONG if strong else _WEAK if analysis.signs else 0.0
    rules = url.score if url and url.score else 0.0
    # The fixed link rules, such as a bare IP address or a hidden destination, count up to Moderate.
    score = max(score, min(_RULES_CAP, rules) if rules >= _WEAK else 0.0)
    evidence = [item.why for item in analysis.signs]
    if analysis.model_score is not None and analysis.model_score >= LINK_MODEL_LINE and not analysis.lookalike.owned_by:
        score = max(score, _WEAK)
        evidence.append(f"The link model scored this host {analysis.model_score:.3f}, above its line of {LINK_MODEL_LINE}.")
    evidence += [line for line in (url.evidence if url else []) if not line.startswith("Link warning sign:")] if rules >= _WEAK else []
    if analysis.live_failed:
        # The user asked for the live checks, so an address alone can't read as a clean result.
        failed = [
            label
            for label, part in (("redirects", analysis.redirects), ("domain age", analysis.domain), ("page", analysis.page))
            if part.status is ModuleStatus.UNAVAILABLE
        ]
        note = f"Could not finish: {', '.join(failed)}. Only the address was scored."
        return RiskComponent(status=ModuleStatus.COMPLETE, counted=True, blocks_low=True, score=score, evidence=evidence, note=note, **base)
    return RiskComponent(status=ModuleStatus.COMPLETE, counted=True, score=score, evidence=evidence, **base)


def _shown_only(
    name: str, label: str, evidence: list[str], *, status: ModuleStatus = ModuleStatus.COMPLETE, note: str = _NOT_MEASURED
) -> RiskComponent:
    return RiskComponent(name=name, label=label, status=status, counted=False, blocks_low=bool(evidence), weight=0.0, evidence=evidence, note=note)


def _link_trust(link: LinkAnalysis | None, url: ModuleResult | None) -> tuple[int, str] | None:
    """Positive evidence about a clean link, which is the one way to score above 50. Never proof."""
    if link is None or link.signs or link.live_failed or (url and url.score):
        return None
    if link.model_score is not None and link.model_score >= LINK_MODEL_LINE:
        return None
    threats = link.threat_lists
    clean = threats.status is ModuleStatus.COMPLETE and not threats.listed
    age = link.domain.age_days
    if link.lookalike.owned_by:
        return 90, f"This domain belongs to {link.lookalike.owned_by}, and no warning sign was found."
    if clean and age is not None and age >= _ESTABLISHED_DAYS:
        return 85, f"The domain is {age // 365} years old, isn't on the threat feeds, and showed no warning sign."
    if clean and age is not None and age >= _YEAR_DAYS:
        return 70, f"The domain is {age // 365} year(s) old, isn't on the threat feeds, and showed no warning sign."
    if clean:
        return 60, "It isn't on the threat feeds and showed no warning sign. Tick the search box to also check the domain's age."
    return None


def _apply_sources(vote: dict, sources: dict | None) -> dict:
    """Let what source search really found outweigh the detectors, as it is stronger evidence."""
    result = {**vote, "raw_mean": vote["mean"]}
    if not sources:
        return result
    earliest, domains = sources.get("earliest"), sources.get("domains", 0)
    if earliest and earliest < BEFORE_IMAGE_GENERATORS:
        result.update(
            mean=vote["mean"] * _OLD_IMAGE_FACTOR,
            level=RiskLevel.INCONCLUSIVE,
            source_note=f"The same image was found dated {earliest}, before DALL-E 2 ({BEFORE_IMAGE_GENERATORS}), so it is unlikely to come from recent image generators. Page dates can be wrong.",
        )
    elif domains >= _WIDE_DOMAINS and vote["flagged"] < vote["total"]:
        result.update(
            mean=vote["mean"] * _WIDE_IMAGE_FACTOR,
            level=RiskLevel.MODERATE,
            source_note=f"The same image is on {domains} sites and the detectors disagree, so this is unclear. Being widely shared doesn't make an image real.",
        )
    return result


def build_unified_risk(
    *,
    media_vote: dict | None = None,
    source_evidence: dict | None = None,
    **given,
) -> UnifiedRisk:
    """Build the result. With a detector vote, the score is the detectors' real output, in decimals."""
    vote = _apply_sources(media_vote, source_evidence) if media_vote else None
    result = _build_unified_risk(media_vote=vote, **given)
    if vote:
        others = [item for item in result.components if item.counted and item.name != "media" and item.score]
        media_trust = round(100 * (1 - vote["mean"]), 2)
        result.trust_score = min(result.trust_score, media_trust) if others and result.trust_score is not None else media_trust
        extra = f" {vote['source_note']}" if vote.get("source_note") else ""
        result.trust_note = (
            f"AI likelihood {vote['raw_mean'] * 100:.2f}%, the average of 3 detectors, and {vote['flagged']} of {vote['total']} flagged it."
            f"{extra} A high score isn't proof of being real, as detectors miss many fakes."
        )
    return result


def _build_unified_risk(
    *,
    text: ModuleResult | None,
    url: ModuleResult | None,
    media: ModuleResult | None,
    media_level: RiskLevel | None = None,
    network: ModuleResult | None = None,
    claims: list | None,
    claim_analysis: ClaimAnalysis | None,
    scam_analysis: ScamAnalysis | None,
    link_analysis: LinkAnalysis | None,
    cross_modal: CrossModalAnalysis | None,
    text_model_score: float | None = None,
    media_vote: dict | None = None,
) -> UnifiedRisk:
    weights = load_weights()
    if media_vote and media:
        # The detectors' majority replaces any single one, which often disagrees with the rest.
        media_level = media_vote.get("level") or (RiskLevel.HIGH if media_vote["flagged"] * 2 > media_vote["total"] else RiskLevel.INCONCLUSIVE)
        media = media.model_copy(update={"score": media_vote["mean"]})
    # Real model scores set the final figure, so it isn't only a table of fixed points.
    model_scores = {
        "link": link_analysis.model_score if link_analysis else None,
        "text": text_model_score,
        "media": media.score if media and media.status is ModuleStatus.COMPLETE else None,
    }
    factor = 1.0
    for name, value in model_scores.items():
        if value is not None:
            factor *= 1 - _MODEL_WEIGHTS[name] * value
    used = ", ".join(f"{name} {value:.3f}" for name, value in model_scores.items() if value is not None)
    how = f" Adjusted by model scores: {used}." if used else ""
    language = [line for line in (text.evidence if text else []) if " rule" not in line and not line.startswith(("Scam warning sign", "Possible inconsistency", "Media and caption"))]
    refuted = [record.text for record in claims or [] if getattr(record.verdict, "value", None) == "contradicted"]
    conflicts = [item.explanation for item in (claim_analysis.inconsistencies if claim_analysis else []) if item.severity == "conflict"]
    components = [
        _with_vote(_media(media, media_level, weights), media_vote),
        _scam(scam_analysis, weights),
        _link(link_analysis, url, weights),
        _shown_only("language", "Language rules", language),
        _shown_only("claims", "Claims contradicted by sources", refuted),
        _shown_only("inconsistency", "Inconsistent statements", conflicts),
        _shown_only("cross_modal", "Caption and media differences", [item.explanation for item in cross_modal.conflicts] if cross_modal else []),
        _shown_only(
            "spread",
            "Spread",
            [],
            status=network.status if network else ModuleStatus.NOT_APPLICABLE,
            note="Not scored, because how something spreads says nothing about whether it is true.",
        ),
    ]
    counted = [item for item in components if item.counted]
    if not counted:
        return UnifiedRisk(
            level=RiskLevel.INCONCLUSIVE,
            trust_score=round(NEUTRAL_TRUST * factor, 1) if used else None,
            components=components,
            weights=weights,
            trust_note=f"Starts from a neutral 50.{how}" if used else "No trust score, because nothing measured reached a result.",
            reason="No measured check reached a result.",
        )
    remaining = 1.0
    for item in counted:
        remaining *= 1 - item.weight * (item.score or 0.0)
    score = round(1 - remaining, 3)
    level = _level(score)
    holding = [item.label for item in components if item.blocks_low]
    reason = None
    if level is RiskLevel.LOW and holding:
        level = RiskLevel.INCONCLUSIVE
        reason = f"The measured checks stayed low, but this needs a person's review: {', '.join(holding)}."
    trust = min(NEUTRAL_TRUST, _TRUST_CAPS.get(level, NEUTRAL_TRUST), 100 - round(score * 100))
    positive = _link_trust(link_analysis, url) if level is RiskLevel.LOW else None
    if positive:
        return UnifiedRisk(
            level=level,
            score=score,
            trust_score=round(positive[0] * factor, 1),
            trust_note=f"{positive[1]}{how} This is a signal, not a guarantee.",
            components=components,
            weights=weights,
        )
    return UnifiedRisk(
        level=level,
        score=score,
        trust_score=round(trust * factor, 1),
        trust_note=f"At most 50, because no check here can show that content is genuine.{how}",
        components=components,
        weights=weights,
        reason=reason,
    )


def summary_for(risk: UnifiedRisk) -> str:
    if risk.level is RiskLevel.INCONCLUSIVE:
        return f"Inconclusive. {risk.reason} This is a triage signal, not a factual verdict."
    return f"Measured signals suggest {risk.level.value} risk. This is a triage signal, not a factual verdict."
