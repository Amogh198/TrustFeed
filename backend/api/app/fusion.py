"""Combines module results and generates evidence-bound action packets."""

import json
import os
from collections.abc import Iterable, Mapping
from importlib import import_module
from typing import Any

from backend.api.app.models import ActionPacketSection, AnalysisResponse, RiskLevel
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


def _parse_action_packet(text: str) -> dict[str, Any]:
    """Accept a Gemini JSON response, including a markdown-fenced fallback."""
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("\n", 1)[1] if "\n" in candidate else ""
        candidate = candidate.removesuffix("```")
    payload = json.loads(candidate.strip())
    if not isinstance(payload, dict):
        raise TypeError("Gemini action packet must be a JSON object")
    return payload


def _generate_with_gemini(
    *,
    api_key: str,
    evidence: list[str],
    overall_risk: str,
    audience: str,
) -> tuple[str, list[ActionPacketSection]]:
    """Generate a structured countermeasure draft from the recorded case signals."""
    prompt = f"""
You are a Trust & Safety expert preparing an evidence-based countermeasure action packet.
The intended audience is: {audience!r}
The case risk label is: {overall_risk!r}
Recorded evidence indicators are: {json.dumps(evidence)}

Do not claim that content is false, illegal, coordinated, or policy-violating unless the recorded
evidence explicitly establishes it. Treat the indicators as leads for human review, not proof.
Produce only valid JSON with this exact shape:
{{
  "draft": "a concise public information note",
  "sections": [
    {{"heading": "Platform takedown notice", "items": ["..."]}},
    {{"heading": "Counter-narrative post", "items": ["..."]}},
    {{"heading": "Internal policy report", "items": ["..."]}}
  ]
}}
Every section should be actionable, measured, and appropriate for the intended audience.
""".strip()
    genai = import_module("google.generativeai")
    configure_name = "configure"
    model_factory_name = "GenerativeModel"
    configure = getattr(genai, configure_name)
    model_factory = getattr(genai, model_factory_name)
    configure(api_key=api_key)
    model = model_factory(os.getenv("GEMINI_MODEL", "gemini-1.5-flash"))
    response = model.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json", "temperature": 0.2},
    )
    payload = _parse_action_packet(response.text)
    draft = payload.get("draft")
    raw_sections = payload.get("sections")
    if not isinstance(draft, str) or not draft.strip() or not isinstance(raw_sections, list):
        raise ValueError("Gemini response is missing the required action-packet fields")
    sections = [ActionPacketSection.model_validate(section) for section in raw_sections]
    if not sections:
        raise ValueError("Gemini response contains no action-packet sections")
    return draft.strip(), sections


def generate_action_packet(
    case: AnalysisResponse,
    audience: str,
    evidence: list[str],
) -> tuple[str, list[ActionPacketSection]] | None:
    """Return Gemini output when configured; failures keep the caller's local template."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        return _generate_with_gemini(
            api_key=api_key,
            evidence=evidence,
            overall_risk=case.overall_risk.value,
            audience=audience,
        )
    except Exception:  # noqa: BLE001 - the optional provider must not block the local fallback.
        # The local evidence-bound packet remains available if the optional provider fails.
        return None
