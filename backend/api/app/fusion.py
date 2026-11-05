"""Combines module results into one triage level. It is never a verdict on truth."""

from collections.abc import Iterable, Mapping

from backend.api.app.models import RiskLevel
from backend.media.models import Assessment, MediaAnalysisResult, ModelBand

_ORDER = (RiskLevel.LOW, RiskLevel.MODERATE, RiskLevel.HIGH, RiskLevel.CRITICAL)
# Results this many levels apart are reported as a disagreement between modules.
_DISAGREEMENT_LEVELS = 2


def media_risk(result: MediaAnalysisResult) -> RiskLevel:
    """Map the media lane's assessment to a level, capped below critical.

    The raw score is not used: a video whose keyframes disagree can have a high
    score and still be inconclusive. Model scores are uncalibrated, so they never
    reach critical on their own.

    "No strong signals" counts as inconclusive, not low. In the benchmark the detector
    scored 128 of 157 fakes in its low band, so a quiet detector doesn't lower the risk.
    """
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


def disagreement_note(levels: Mapping[str, RiskLevel]) -> str | None:
    """Say when modules that reached a result are at least two levels apart.

    The overall level still follows the strongest signal, so a quiet module can't hide
    a loud one. This makes the conflict visible for the person reviewing the case.
    """
    known = {name: level for name, level in levels.items() if level is not RiskLevel.INCONCLUSIVE}
    if len(known) < 2:
        return None
    lowest = min(known, key=lambda name: _ORDER.index(known[name]))
    highest = max(known, key=lambda name: _ORDER.index(known[name]))
    if _ORDER.index(known[highest]) - _ORDER.index(known[lowest]) < _DISAGREEMENT_LEVELS:
        return None
    return (
        f"The checks disagree: {highest} suggests {known[highest].value} risk while {lowest} suggests "
        f"{known[lowest].value}. The overall level follows the stronger signal, so please review both."
    )


def fused_summary(level: RiskLevel) -> str:
    if level is RiskLevel.INCONCLUSIVE:
        return "The available checks do not support a clear triage result."
    return f"Available signals suggest {level.value} risk; this is a triage signal, not a factual verdict."
