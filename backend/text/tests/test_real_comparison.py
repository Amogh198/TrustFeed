"""Run the real comparison models when they are downloaded. Skipped otherwise, and offline either way."""

import pytest

from backend.text.verify_models import HuggingFaceComparer

comparer = HuggingFaceComparer()
pytestmark = pytest.mark.skipif(comparer.is_ready() is not None, reason="The comparison models have not been downloaded")


def test_related_passages_score_higher_than_unrelated_ones():
    related, unrelated = comparer.similarity(
        "The Eiffel Tower is in Paris.",
        ["The Eiffel Tower is a wrought-iron lattice tower in Paris, France.", "Mangoes are grown across the country."],
    )
    assert related > 0.6
    assert unrelated < 0.35


@pytest.mark.parametrize(
    ("premise", "claim", "strongest"),
    [
        ("The Eiffel Tower is a wrought-iron lattice tower in Paris, France.", "The Eiffel Tower is in Paris.", "entailment"),
        ("The Eiffel Tower is a wrought-iron lattice tower in Paris, France.", "The Eiffel Tower is in Berlin.", "contradiction"),
        ("Mumbai is the financial capital of India.", "A bridge collapsed in Mumbai on 5 March 2024.", "neutral"),
    ],
)
def test_entailment_labels_are_read_correctly(premise, claim, strongest):
    score = comparer.entail([(premise, claim)])[0]
    values = {"entailment": score.entailment, "neutral": score.neutral, "contradiction": score.contradiction}
    assert max(values, key=lambda name: values[name]) == strongest
