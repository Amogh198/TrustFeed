"""Combines module results and generates evidence-bound action packets."""

import json
import logging
import os
from collections.abc import Iterable, Mapping
from typing import Any

from backend.api.app.explanation import build_countermeasures
from backend.api.app.models import (
    ActionPacketResponse,
    ActionPacketSection,
    AnalysisResponse,
    RiskLevel,
)
from backend.media.models import Assessment, MediaAnalysisResult, ModelBand

logger = logging.getLogger(__name__)

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


def _case_evidence(case: AnalysisResponse) -> list[str]:
    """Collect the recorded evidence without adding unsupported references."""
    return [item for module in case.modules.values() for item in module.evidence]


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


def _fallback_packet(case: AnalysisResponse, audience: str = "public") -> ActionPacketResponse:
    """Static fallback template assembled by fixed rules."""
    evidence = _case_evidence(case)
    sections = [
        ActionPacketSection(
            heading="Assessment",
            items=[case.summary, f"Risk level: {case.overall_risk.value}. This is a triage signal, not a factual verdict."],
        ),
        ActionPacketSection(
            heading="Evidence observed",
            items=evidence or ["No module produced evidence for this case."],
        ),
        ActionPacketSection(
            heading="Claim status",
            items=(
                [f"{claim.text} — {claim.verdict.value}; {claim.rationale}" for claim in case.claims]
                or ["No text claim was supplied for atomization."]
            ),
        ),
        ActionPacketSection(heading="Uncertainties", items=case.uncertainties or ["No additional uncertainty was recorded."]),
        ActionPacketSection(heading="Recommended next actions", items=case.recommended_actions),
        ActionPacketSection(heading="Suggested countermeasures", items=build_countermeasures(case)),
    ]
    draft_lines = [
        f"TrustFeed draft for {audience}.",
        "This draft is assembled by fixed rules from the case record; no generative model or external fact-check was used.",
    ]
    for section in sections:
        draft_lines.append(f"\n{section.heading}:")
        draft_lines.extend(f"- {item}" for item in section.items)
    return ActionPacketResponse(
        case_id=case.case_id,
        generated=False,
        label="Assembled by fixed rules from this case's evidence; no generative model or external verification was used.",
        draft="\n".join(draft_lines),
        evidence_references=evidence,
        sections=sections,
    )


def _generate_with_gemini(
    *,
    api_key: str,
    evidence: list[str],
    overall_risk: str,
    audience: str,
) -> tuple[str, list[ActionPacketSection]]:
    """Request a concise, machine-readable action packet from Gemini."""
    import google.generativeai as genai

    prompt = f"""
You are an expert Trust & Safety countermeasure system.
Analyze the following case signals and generate an actionable countermeasure Action Packet.

Case Risk Level: {overall_risk!r}
Intended Audience: {audience!r}
Recorded Evidence Indicators:
{json.dumps(evidence, indent=2)}

Do not claim that content is false, illegal, coordinated, or policy-violating unless the recorded
evidence explicitly establishes it. Treat indicators as leads for review, not absolute proof.

Produce only valid JSON with this exact shape:
{{
  "draft": "A comprehensive draft summary and communication note tailored for {audience}.",
  "sections": [
    {{
      "heading": "Platform Takedown Notice",
      "items": [
        "Specific actionable points for platform moderators citing observed evidence",
        "Recommended policy enforcement actions"
      ]
    }},
    {{
      "heading": "Counter-Narrative Post",
      "items": [
        "A public factual correction message addressing the misleading claims",
        "Direct clarification citing verified details"
      ]
    }},
    {{
      "heading": "Recommended Next Actions",
      "items": [
        "Immediate containment steps",
        "Ongoing monitoring advice"
      ]
    }}
  ]
}}
Only output the valid JSON object.
""".strip()

    genai.configure(api_key=api_key)  # pyright: ignore[reportPrivateImportUsage]
    model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-1.5-flash"))  # pyright: ignore[reportPrivateImportUsage]
    response = model.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json", "temperature": 0.2},
    )
    payload = _parse_action_packet(response.text)
    draft = payload.get("draft")
    raw_sections = payload.get("sections")
    if not isinstance(draft, str) or not draft.strip() or not isinstance(raw_sections, list):
        raise ValueError("Gemini response is missing required fields")
    sections = [ActionPacketSection.model_validate(s) for s in raw_sections]
    if not sections:
        raise ValueError("Gemini response contains no sections")
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
    except Exception:
        logger.warning("Gemini action packet generation failed; falling back to static template", exc_info=True)
        return None


def action_packet(
    case_or_id: Any,
    request_or_audience: Any = "public",
    cases: Mapping[str, AnalysisResponse] | None = None,
) -> ActionPacketResponse:
    """Generate an action packet when Gemini is configured, otherwise use the local template."""
    if isinstance(case_or_id, AnalysisResponse):
        case = case_or_id
    elif isinstance(case_or_id, str):
        if cases and case_or_id in cases:
            case = cases[case_or_id]
        else:
            from backend.api.app.store import default_store
            saved = default_store().get(case_or_id)
            if saved is None:
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="Case not found in this server process")
            case = saved
    else:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Invalid case parameter")

    audience = getattr(request_or_audience, "audience", request_or_audience)
    if not isinstance(audience, str) or not audience.strip():
        audience = "public"

    evidence = _case_evidence(case)
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return _fallback_packet(case, audience)

    try:
        draft, sections = _generate_with_gemini(
            api_key=api_key,
            evidence=evidence,
            overall_risk=case.overall_risk.value,
            audience=audience,
        )
        return ActionPacketResponse(
            case_id=case.case_id,
            generated=True,
            label="AI-generated draft; review against the recorded evidence before use.",
            draft=draft,
            evidence_references=evidence,
            sections=sections,
        )
    except Exception as exc:  # noqa: BLE001 - the optional provider must not block the local fallback.
        logger.warning("Gemini action packet generation failed (%s); falling back to static template", exc)
        return _fallback_packet(case, audience)
