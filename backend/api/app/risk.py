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
_STRONG = 0.7
_WEAK = 0.3
# One uncalibrated model never reaches critical alone.
_MEDIA_CAP = 0.75
_ELEVATED = 0.75
_THRESHOLDS = ((0.8, RiskLevel.CRITICAL), (0.6, RiskLevel.HIGH), (0.3, RiskLevel.MODERATE))
_TRUST_CAPS = {RiskLevel.MODERATE: 40, RiskLevel.HIGH: 25, RiskLevel.CRITICAL: 25}
_NOT_MEASURED = "Not scored, because this has not been measured on labelled data."


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
        # The benchmark describes scored images, so it says nothing about a check that gave no score.
        base["results_file"] = None
        note = "An audio file gets no media score." if module.status is ModuleStatus.COMPLETE else (module.limitations[0] if module.limitations else "The media check gave no result.")
        return RiskComponent(status=ModuleStatus.UNAVAILABLE, counted=False, blocks_low=True, note=note, **base)
    # The media check's own assessment decides, as a video whose frames disagree can score high and still be unclear.
    if level not in (RiskLevel.MODERATE, RiskLevel.HIGH):
        # In the benchmark it scored most fakes low, so a quiet detector says nothing either way.
        return RiskComponent(
            status=ModuleStatus.COMPLETE,
            counted=False,
            blocks_low=True,
            score=module.score,
            note="No strong signal. The detector misses many fakes, so this neither raises nor lowers the risk.",
            **base,
        )
    score = min(_MEDIA_CAP, module.score) if level is RiskLevel.HIGH else max(_WEAK, min(module.score, _ELEVATED - 0.01))
    return RiskComponent(status=ModuleStatus.COMPLETE, counted=True, score=score, **base)


def _scam(analysis: ScamAnalysis | None, weights: Mapping[str, float]) -> RiskComponent:
    base = {"name": "scam", "label": "Scam warning signs", "weight": weights["scam"], "results_file": SCAM_RESULTS}
    if analysis is None:
        return RiskComponent(status=ModuleStatus.NOT_APPLICABLE, counted=False, note="No text was submitted.", **base)
    score = _STRONG if analysis.assessment == WARNING_SIGNS else 0.0 if analysis.assessment == NONE_FOUND else _WEAK
    return RiskComponent(
        status=ModuleStatus.COMPLETE, counted=True, score=score, evidence=[f"{item.why} Found: {item.quote!r}" for item in analysis.signs], **base
    )


def _link(analysis: LinkAnalysis | None, weights: Mapping[str, float]) -> RiskComponent:
    base = {"name": "link", "label": "Link address check", "weight": weights["link"], "results_file": LINK_RESULTS}
    if analysis is None:
        return RiskComponent(status=ModuleStatus.NOT_APPLICABLE, counted=False, note="No link was submitted.", **base)
    strength = analysis.lookalike.strength
    score = _STRONG if strength == "strong" else _WEAK if strength == "weak" else 0.0
    evidence = [item.why for item in analysis.signs if item.sign.startswith("lookalike_")]
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


def build_unified_risk(
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
) -> UnifiedRisk:
    weights = load_weights()
    language = [line for line in (text.evidence if text else []) if " rule" not in line and not line.startswith(("Scam warning sign", "Possible inconsistency", "Media and caption"))]
    refuted = [record.text for record in claims or [] if getattr(record.verdict, "value", None) == "contradicted"]
    conflicts = [item.explanation for item in (claim_analysis.inconsistencies if claim_analysis else []) if item.severity == "conflict"]
    link_other = [item.why for item in (link_analysis.signs if link_analysis else []) if not item.sign.startswith("lookalike_")]
    url_rules = [line for line in (url.evidence if url else []) if url is not None and not line.startswith("Link warning sign:") and (url.score or 0) >= _WEAK]
    components = [
        _media(media, media_level, weights),
        _scam(scam_analysis, weights),
        _link(link_analysis, weights),
        _shown_only("language", "Language rules", language),
        _shown_only("link_rules", "Link rules and live link signs", [*url_rules, *link_other]),
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
            components=components,
            weights=weights,
            trust_note="No trust score, because nothing measured reached a result.",
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
    return UnifiedRisk(
        level=level,
        score=score,
        trust_score=trust,
        trust_note="At most 50, because no check here can show that content is genuine. 50 is a neutral midpoint, not a measurement.",
        components=components,
        weights=weights,
        reason=reason,
    )


def summary_for(risk: UnifiedRisk) -> str:
    if risk.level is RiskLevel.INCONCLUSIVE:
        return f"Inconclusive. {risk.reason} This is a triage signal, not a factual verdict."
    return f"Measured signals suggest {risk.level.value} risk. This is a triage signal, not a factual verdict."
