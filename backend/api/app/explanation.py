"""Builds the case explanation and the countermeasures from what the modules really found."""

from typing import Any

from backend.api.app.models import (
    AnalysisResponse,
    ExplanationCheck,
    ExplanationResponse,
    MissingCheck,
    ModuleResult,
    ModuleStatus,
    RiskLevel,
)
from backend.text.links import link_checks

_NOT_PROOF = "A score is a signal for review, not proof."
_RULE_LABELS = {"text": "Text language rules", "url": "Link rules"}
# Above this the media detector's band is "elevated".
_MEDIA_ELEVATED = 0.75


def _module(case: AnalysisResponse, name: str) -> ModuleResult:
    """Read a module, as a case saved before that module existed won't have it."""
    return case.modules.get(name) or ModuleResult(
        status=ModuleStatus.NOT_APPLICABLE, limitations=["This case was saved before this check existed."]
    )


def _rule_check(name: str, module: ModuleResult) -> ExplanationCheck:
    found = len(module.evidence)
    return ExplanationCheck(
        check_id=f"{name}.rules",
        module=name,
        label=_RULE_LABELS[name],
        status=module.status.value,
        result=f"{found} pattern(s) matched, score {module.score:.2f} out of 1." if module.score is not None else "No score.",
        reasoning=(
            "; ".join(module.evidence) if found else "None of the fixed patterns matched."
        ),
        limitations=[*module.limitations, _NOT_PROOF],
    )


def _submitted(case: AnalysisResponse) -> list[str]:
    """Name the kinds of content received, without repeating the content."""
    kinds = {"text": "Text", "url": "A link", "media": "An image or video"}
    submitted = [label for name, label in kinds.items() if _module(case, name).status is not ModuleStatus.NOT_APPLICABLE]
    return submitted or ["No content was submitted. This is a demonstration case."]


def _supports(case: AnalysisResponse) -> list[str]:
    """List what raises concern. Each item is a signal for review, not proof."""
    lines = [*_module(case, "text").evidence, *_module(case, "url").evidence]
    media = _module(case, "media")
    if media.score is not None and media.score >= _MEDIA_ELEVATED:
        lines.append(f"The media detector scored {media.score:.2f} out of 1, in its elevated band.")
    network = _module(case, "network")
    if network.score is not None:
        lines.append(f"A group of accounts repeatedly co-shared items, with a heuristic score of {network.score:.2f}.")
    return lines


def _refutes(case: AnalysisResponse) -> list[str]:
    """List checks that found nothing. A quiet media detector is left out, as it isn't reassuring."""
    lines = []
    for name in ("text", "url"):
        module = _module(case, name)
        if module.status is ModuleStatus.COMPLETE and not module.evidence:
            lines.append(f"{_RULE_LABELS[name]} matched nothing, which does not show the content is genuine.")
    return lines


def _missing(case: AnalysisResponse, checks: list[ExplanationCheck]) -> list[MissingCheck]:
    covered = {check.module for check in checks}
    missing = []
    for name, module in case.modules.items():
        if name not in covered:
            reason = module.limitations[0] if module.limitations else f"This check is {module.status.value}."
            missing.append(MissingCheck(module=name, status=module.status.value, reason=reason))
    return missing


def build_explanation(
    case: AnalysisResponse,
    media_checks: list[dict[str, Any]],
    provenance_checks: list[dict[str, Any]],
    network_checks: list[dict[str, Any]],
) -> ExplanationResponse:
    """Merge every lane's checks. Anything not run is listed as missing, never filled in."""
    checks = [
        _rule_check(name, _module(case, name))
        for name in ("text", "url")
        if _module(case, name).status is ModuleStatus.COMPLETE
    ]
    if case.link_analysis:
        checks += [ExplanationCheck.model_validate(check) for check in link_checks(case.link_analysis)]
    checks += [ExplanationCheck.model_validate(check) for check in [*media_checks, *provenance_checks, *network_checks]]
    return ExplanationResponse(
        case_id=case.case_id,
        what_was_submitted=_submitted(case),
        what_was_detected=[case.summary],
        supports=_supports(case),
        refutes=_refutes(case),
        uncertainties=case.uncertainties,
        checks=checks,
        missing_checks=_missing(case, checks),
    )


def build_countermeasures(case: AnalysisResponse) -> list[str]:
    """Choose next steps from what this case actually shows."""
    actions: list[str] = []
    text_evidence = " ".join(_module(case, "text").evidence)
    if "scam-pattern" in text_evidence:
        actions.append("Do not send money, passwords or one-time codes. Warn people who received this message.")
    if "health claim" in text_evidence:
        actions.append("Do not follow this health advice. Check it with a qualified doctor or a public health authority.")
    if "Urgency" in text_evidence or "conspiracy" in text_evidence:
        actions.append("Pause before forwarding. Pressure to share quickly is a common manipulation pattern.")
    url = _module(case, "url")
    if url.score and url.score >= 0.3:
        actions.append("Do not open this link or enter any details. Report it to the platform or a cybercrime authority.")
    media = _module(case, "media")
    if media.status is ModuleStatus.COMPLETE:
        if media.score is not None and media.score >= _MEDIA_ELEVATED:
            actions.append("Have a person review this media, and ask the sharer for the original file.")
        else:
            actions.append(
                "Don't treat this media as authentic because of a low score. Ask for the original file and check its context."
            )
    if _module(case, "provenance").status is ModuleStatus.COMPLETE:
        actions.append("Compare the date claimed for this image with the earliest appearance found, and note the caveat.")
    if _module(case, "network").score is not None:
        actions.append(
            "Ask the platforms' trust and safety teams to review the flagged accounts. This is a signal, not proof of coordination."
        )
    if case.claims:
        actions.append("Check each listed claim with a trusted source. None has been verified by this tool.")
    if case.overall_risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
        actions.append("Prepare a short public correction once a person has confirmed the findings.")
    return actions or ["No specific signal was found. Check the content with a trusted source before relying on it."]
