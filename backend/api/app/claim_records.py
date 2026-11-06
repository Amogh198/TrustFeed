"""Turn the text lane's claim report into API records."""

from dataclasses import asdict

from backend.api.app.models import (
    ClaimAnalysis,
    ClaimEntity,
    ClaimInconsistency,
    ClaimRecord,
    ClaimSource,
    ClaimVerdict,
    ClaimVerification,
    ModuleStatus,
    VerificationProvider,
)
from backend.text.claim_report import analyze_claims
from backend.text.claims import AnalyzedClaim
from backend.text.verification import VerificationReport, verify_claims


def _entities(claim: AnalyzedClaim) -> list[ClaimEntity]:
    entities = [ClaimEntity(text=item.text, type="date", value=item.value) for item in claim.dates]
    entities += [
        ClaimEntity(text=item.text, type="number", value=f"{item.value:g}", unit=item.unit, bound=item.bound)
        for item in claim.numbers
    ]
    entities += [ClaimEntity(text=item.text, type=item.type, source="model", score=item.score) for item in claim.named]
    return entities


def _verification_summary(report: VerificationReport) -> ClaimVerification:
    return ClaimVerification(
        status=ModuleStatus(report.status),
        reason=report.reason,
        comparison_status=ModuleStatus(report.comparison_status),
        comparison_reason=report.comparison_reason,
        providers=[
            VerificationProvider(
                name=item.name, status=ModuleStatus(item.status), reason=item.reason, result_count=len(item.documents)
            )
            for item in report.providers
        ],
        skipped_claims=report.skipped_claims,
        limitations=report.limitations,
    )


def build_claims(units: list[str], *, search_web: bool = False) -> tuple[list[ClaimRecord], ClaimAnalysis | None]:
    """``search_web`` sends search words to outside services, so only a user's opt-in may set it."""
    if not units:
        return [], None
    report = analyze_claims(units)
    verification = verify_claims(report.claims) if search_web else None
    verdicts = {item.claim_id: item for item in verification.verdicts} if verification else {}

    records: list[ClaimRecord] = []
    for claim in report.claims:
        record = ClaimRecord(
            id=claim.id, text=claim.text, kind=claim.kind, checkable=claim.checkable, entities=_entities(claim)
        )
        verdict = verdicts.get(claim.id)
        if verdict:
            record.verdict = ClaimVerdict(verdict.verdict)
            record.rationale = verdict.rationale
            record.sources = [ClaimSource(**asdict(source)) for source in verdict.sources]
        records.append(record)

    analysis = ClaimAnalysis(
        verification=_verification_summary(verification) if verification else ClaimVerification(),
        entity_model_status=ModuleStatus(report.ner_status),
        entity_model_reason=report.ner_reason,
        inconsistencies=[
            ClaimInconsistency(
                id=item.id,
                kind=item.kind,
                severity=item.severity,
                claim_ids=list(item.claim_ids),
                explanation=item.explanation,
            )
            for item in report.inconsistencies
        ],
        omitted_claims=report.omitted_claims,
        limitations=report.limitations,
    )
    return records, analysis
