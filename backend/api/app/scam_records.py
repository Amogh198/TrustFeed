"""Turn the scam rules and the optional model into an API record."""

import os

from backend.api.app.models import ModuleStatus, ScamAnalysis, ScamSignRecord
from backend.text.scam_model import PhishingOutcome, default_runner
from backend.text.scams import find_signs

RESULTS_FILE = "backend/text/evaluation/results/scam_eval_test.json"
MODEL_OFF_REASON = (
    "This model is off by default, because it flagged too many legitimate posts on our labelled examples. "
    f"See {RESULTS_FILE}."
)
LIMITATIONS = [
    "Finding no warning sign does not mean something is safe. Scammers change their wording.",
    "A warning sign is a reason to look closer, not proof of a scam.",
    "These rules are mostly in English, with very little Hindi and no other languages.",
]


def _model_outcome(text: str) -> PhishingOutcome:
    # Set by whoever runs the server, never by a request.
    if os.getenv("TEXT_SCAM_MODEL_ENABLED", "").casefold() not in {"1", "true", "yes"}:
        return PhishingOutcome("unavailable", MODEL_OFF_REASON)
    return default_runner().run(text)


def build_scam_analysis(text: str) -> ScamAnalysis:
    report = find_signs(text)
    model = _model_outcome(text)
    return ScamAnalysis(
        assessment=report.assessment,
        categories=report.categories,
        signs=[
            ScamSignRecord(sign=item.sign, category=item.category, strength=item.strength, why=item.why, quote=item.quote)
            for item in report.signs
        ],
        model_status=ModuleStatus(model.status),
        model_reason=model.reason,
        model_score=model.score,
        results_file=RESULTS_FILE,
        limitations=LIMITATIONS,
    )
