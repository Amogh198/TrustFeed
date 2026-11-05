"""Turn the text lane's claim report into API records."""

from backend.api.app.models import (
    ClaimAnalysis,
    ClaimEntity,
    ClaimInconsistency,
    ClaimRecord,
    ModuleStatus,
)
from backend.text.claim_report import analyze_claims
from backend.text.claims import AnalyzedClaim


def _entities(claim: AnalyzedClaim) -> list[ClaimEntity]:
    entities = [ClaimEntity(text=item.text, type="date", value=item.value) for item in claim.dates]
    entities += [
        ClaimEntity(text=item.text, type="number", value=f"{item.value:g}", unit=item.unit, bound=item.bound)
        for item in claim.numbers
    ]
    entities += [ClaimEntity(text=item.text, type=item.type, source="model", score=item.score) for item in claim.named]
    return entities


def build_claims(units: list[str]) -> tuple[list[ClaimRecord], ClaimAnalysis | None]:
    if not units:
        return [], None
    report = analyze_claims(units)
    records = [
        ClaimRecord(id=claim.id, text=claim.text, kind=claim.kind, checkable=claim.checkable, entities=_entities(claim))
        for claim in report.claims
    ]
    analysis = ClaimAnalysis(
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
