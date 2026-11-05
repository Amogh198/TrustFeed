"""Combines module results into one triage level. It is never a verdict on truth."""

from collections.abc import Iterable

from backend.api.app.models import RiskLevel
from backend.media.models import Assessment, MediaAnalysisResult, ModelBand

_ORDER = (RiskLevel.LOW, RiskLevel.MODERATE, RiskLevel.HIGH, RiskLevel.CRITICAL)


def media_risk(result: MediaAnalysisResult) -> RiskLevel:
    """Map the media lane's assessment to a level, capped below critical.

    The raw score is not used: a video whose keyframes disagree can have a high
    score and still be inconclusive. Model scores are uncalibrated, so they never
    reach critical on their own.
    """
    if result.assessment is Assessment.NO_STRONG_SIGNALS:
        return RiskLevel.LOW
    if result.assessment is Assessment.SIGNALS_PRESENT:
        elevated = result.checks.classifier.band is ModelBand.ELEVATED
        return RiskLevel.HIGH if elevated else RiskLevel.MODERATE
    return RiskLevel.INCONCLUSIVE


def combine_risks(levels: Iterable[RiskLevel]) -> RiskLevel:
    """Return the strongest level. "Low" needs every module to have reached a result."""
    levels = list(levels)
    known = [level for level in levels if level is not RiskLevel.INCONCLUSIVE]
    if not known:
        return RiskLevel.INCONCLUSIVE
    strongest = max(known, key=_ORDER.index)
    if strongest is RiskLevel.LOW and len(known) != len(levels):
        return RiskLevel.INCONCLUSIVE
    return strongest


def fused_summary(level: RiskLevel) -> str:
    if level is RiskLevel.INCONCLUSIVE:
        return "The available checks do not support a clear triage result."
    return f"Available signals suggest {level.value} risk; this is a triage signal, not a factual verdict."
