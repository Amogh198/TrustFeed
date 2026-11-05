"""Claim splitting, entities and inconsistency checks. No model or network is used."""

import threading
from datetime import UTC, datetime

import pytest

from backend.text.claim_report import analyze_claims
from backend.text.claims import split_claims
from backend.text.entities import find_dates, find_numbers
from backend.text.ner import ModelEntity, NerRunner, NerUnavailable

NOW = datetime(2026, 11, 5, tzinfo=UTC)


class FakeNer:
    """Finds the words it is given, as the model would, so nothing is downloaded."""

    def __init__(self, places=(), people=()):
        self.places, self.people = places, people
        self.calls: list[list[str]] = []

    def is_ready(self):
        return None

    def predict(self, texts):
        self.calls.append(list(texts))
        results = []
        for text in texts:
            found = []
            for names, kind in ((self.places, "place"), (self.people, "person")):
                for name in names:
                    start = text.find(name)
                    if start >= 0:
                        found.append(ModelEntity(name, kind, 0.99, start, start + len(name)))
            results.append(found)
        return results


class MissingNer:
    def is_ready(self):
        return "The model has not been downloaded."

    def predict(self, texts):
        raise AssertionError("A missing model must not be called")


def analyze(text, ner=None):
    backend = ner or MissingNer()
    return analyze_claims(split_claims(text), runner=NerRunner(backend, timeout_seconds=5), now=NOW)


def kinds(text, ner=None):
    return [item.kind for item in analyze(text, ner).inconsistencies]


# Splitting


def test_splitting_keeps_abbreviations_and_decimals_together():
    text = "Dr. Rao said Rs. 2.5 crore was missing. The U.S. embassy closed."
    assert split_claims(text) == ["Dr. Rao said Rs. 2.5 crore was missing.", "The U.S. embassy closed."]


def test_long_sentence_splits_only_where_both_sides_are_statements():
    text = "Police arrested five men in the market, and the court released them on Monday evening."
    assert split_claims(text) == ["Police arrested five men in the market", "the court released them on Monday evening."]
    # The right-hand side has no subject of its own, so this stays one claim.
    whole = "The minister resigned from the cabinet on Friday and left the city with his family."
    assert split_claims(whole) == [whole]
    # A list of things is not two statements.
    items = "The shipment contained rice and wheat and lentils and sugar from several different farms."
    assert split_claims(items) == [items]


def test_repeats_and_list_markers_and_unpunctuated_posts():
    assert split_claims("- The bridge fell.\n- The bridge fell.\n2. The road closed.") == [
        "The bridge fell.",
        "The road closed.",
    ]
    assert split_claims("the bridge fell down near the station") == ["the bridge fell down near the station"]
    assert split_claims("   ") == []


def test_hindi_sentence_mark_splits():
    assert len(split_claims("पुल गिर गया। सड़क बंद है।")) == 2


# What kind of statement it is


@pytest.mark.parametrize(
    ("text", "kind", "checkable"),
    [
        ("Did the bridge fall?", "question", False),
        ("Share this now!", "call_to_action", False),
        ("Please forward this to everyone.", "call_to_action", False),
        ("Share prices fell sharply on Tuesday.", "factual", True),
        ("I think the mayor is lying about everything.", "opinion", False),
        ("The new policy is a disgrace.", "opinion", False),
        ("I think 50 people died there.", "factual", True),
        ("Urgent!", "fragment", False),
        ("The bridge collapsed near the station.", "factual", True),
    ],
)
def test_claim_kinds_use_context(text, kind, checkable):
    claim = analyze(text).claims[0]
    assert (claim.kind, claim.checkable) == (kind, checkable)


# Dates and numbers


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("It fell on 5 March 2024.", "2024-03-05"),
        ("It fell on March 5th, 2024.", "2024-03-05"),
        ("It fell on 2024-03-05.", "2024-03-05"),
        ("It fell on 25/03/2024.", "2024-03-25"),
        ("It fell in March 2024.", "2024-03"),
        ("It fell on 5 March.", "--03-05"),
        ("It fell in 2024.", "2024"),
    ],
)
def test_date_forms(text, value):
    assert [item.value for item in find_dates(text)] == [value]


def test_ambiguous_and_relative_dates_have_no_value():
    assert find_dates("It fell on 05/03/2024.")[0].value is None
    assert find_dates("It fell yesterday.")[0].value is None


def test_ordinary_words_are_not_months():
    assert find_dates("He may march 5 times.") == []


def test_number_values_units_and_hedges():
    text = "At least 1,20,000 people left, about 2 crore was spent, Rs. 500 went missing and turnout was 45%."
    numbers = find_numbers(text, find_dates(text))
    assert [(item.value, item.unit, item.bound) for item in numbers] == [
        (120000.0, "people", "at_least"),
        (20000000.0, None, "approximate"),
        (500.0, "rs", None),
        (45.0, "%", None),
    ]


def test_year_is_not_a_quantity_but_a_count_is():
    assert find_numbers("Ask about 2024.", []) == []
    assert find_numbers("2000 people left.", [])[0].unit == "people"


# Conflicts that should be flagged


def test_same_event_with_different_figures_is_flagged():
    report = analyze("The factory fire killed 50 people. The factory fire killed 200 people.")
    item = report.inconsistencies[0]
    assert (item.kind, item.severity, item.claim_ids) == ("figures", "conflict", ("claim-1", "claim-2"))
    assert "50" in item.explanation and "200" in item.explanation


def test_same_event_on_different_dates_is_flagged():
    assert kinds("The bridge collapsed on 3 March 2024. The bridge collapsed on 5 March 2024.") == ["dates"]


def test_different_dates_for_something_repeatable_is_only_a_note():
    report = analyze("The minister visited the school on 3 March 2024. The minister visited the school on 5 March 2024.")
    assert [(item.kind, item.severity) for item in report.inconsistencies] == [("dates", "note")]


def test_negation_is_flagged():
    assert kinds("The minister resigned from the cabinet. The minister did not resign from the cabinet.") == ["negation"]


def test_different_sources_are_a_note_not_a_conflict():
    report = analyze("Police said 50 people died in the blast. Hospital officials said 200 people died in the blast.")
    assert [(item.kind, item.severity) for item in report.inconsistencies] == [("figures", "note")]
    assert "different sources" in report.inconsistencies[0].explanation


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("The bridge collapsed on 31 February 2024.", "impossible_date"),
        ("The rally began on Monday, 5 March 2024.", "weekday_mismatch"),
        ("The bridge collapsed on 5 March 2030.", "future_date"),
        ("The result showed 120% of voters supported him.", "impossible_share"),
        ("The survey found 500 out of 200 residents agreed.", "part_exceeds_whole"),
    ],
)
def test_single_statement_problems(text, kind):
    assert kinds(text) == [kind]


# Things that look like conflicts and are not


@pytest.mark.parametrize(
    "text",
    [
        # Different things happened.
        "The factory fire killed 50 people. The factory fire injured 200 people.",
        # Different events.
        "50 people attended the rally. 200 people attended the wedding.",
        # Different times.
        "In 2020 the city population was 10 million people. In 2024 the city population was 12 million people.",
        # The figure moved.
        "The fire killed 50 people. The fire has now killed 200 people.",
        "Sales of the phone rose from 50 units to 200 units.",
        # A bound agrees with a figure inside it.
        "The fire killed at least 50 people. The fire killed 200 people.",
        "The fire killed up to 200 people. The fire killed 50 people.",
        "The fire killed about 50 people. The fire killed 52 people.",
        # Different precision of the same date.
        "The bridge collapsed in March 2024. The bridge collapsed on 5 March 2024.",
        # A valid weekday, a future plan, growth over 100% and a normal share.
        "The rally began on Tuesday, 5 March 2024.",
        # The check runs in November 2026, so these can already have happened.
        "The bridge collapsed in 2026.",
        "The bridge collapsed in March 2026.",
        "The bridge will open on 5 March 2030.",
        "The election is scheduled for 5 March 2030.",
        "Profits of the company rose 120% of last year.",
        "The survey found 200 out of 500 residents agreed.",
        # A question and an opinion assert nothing.
        "Did 50 people die in the fire? The fire killed 200 people.",
        # Unrelated statements that only share a number.
        "The bridge is 50 metres long. The temple is 200 metres from the river.",
    ],
)
def test_no_false_alarm(text):
    assert kinds(text) == []


def test_place_conflict_needs_the_model_and_is_only_a_note():
    text = "The factory fire killed 50 people in Mumbai. The factory fire killed 50 people in Pune."
    assert kinds(text) == []
    report = analyze(text, FakeNer(places=("Mumbai", "Pune")))
    assert [(item.kind, item.severity) for item in report.inconsistencies] == [("places", "note")]


def test_same_figures_in_different_places_are_separate_events():
    text = "The factory fire killed 50 people in Mumbai. The factory fire killed 200 people in Pune."
    assert "figures" not in kinds(text, FakeNer(places=("Mumbai", "Pune")))


# The model is optional


def test_missing_model_is_reported_and_rules_still_work():
    report = analyze("The bridge collapsed on 31 February 2024.")
    assert report.ner_status == "unavailable"
    assert report.ner_reason == "The model has not been downloaded."
    assert any("Names and places were not extracted" in item for item in report.limitations)
    assert report.claims[0].named == ()
    assert [item.kind for item in report.inconsistencies] == ["impossible_date"]


def test_model_entities_attach_to_the_right_claim_and_skip_non_claims():
    ner = FakeNer(people=("Rao",), places=("Pune",))
    report = analyze("Did Rao lie? Rao visited the school in Pune on Friday.", ner)
    assert report.ner_status == "complete"
    assert ner.calls == [["Rao visited the school in Pune on Friday."]]
    assert report.claims[0].named == ()
    assert {item.type for item in report.claims[1].named} == {"person", "place"}


def test_no_factual_claims_means_the_model_does_not_run():
    ner = FakeNer()
    report = analyze("Is this true?", ner)
    assert report.ner_status == "not_applicable"
    assert ner.calls == []


class SlowNer(FakeNer):
    def __init__(self):
        super().__init__()
        self.release = threading.Event()

    def predict(self, texts):
        self.release.wait(10)
        return [[] for _ in texts]


def test_slow_model_hits_the_time_limit_and_later_calls_do_not_pile_up():
    backend = SlowNer()
    runner = NerRunner(backend, timeout_seconds=0.05)
    first = runner.run(["The bridge collapsed."])
    assert first.status == "unavailable" and "did not finish within" in (first.reason or "")
    second = runner.run(["The bridge collapsed."])
    assert second.status == "unavailable" and "busy" in (second.reason or "")
    backend.release.set()


class BrokenNer(FakeNer):
    def __init__(self, error):
        super().__init__()
        self.error = error

    def predict(self, texts):
        raise self.error


def test_model_failures_are_reported_without_leaking_detail(caplog):
    secret = "the submitted text"
    outcome = NerRunner(BrokenNer(ValueError(secret))).run([secret])
    assert outcome.status == "unavailable"
    assert secret not in (outcome.reason or "")
    assert secret not in caplog.text
    expected = NerRunner(BrokenNer(NerUnavailable("Packages are not installed."))).run(["text"])
    assert expected.reason == "Packages are not installed."


# Found by running a realistic post, not a sentence written to fit the rules


REALISTIC_POST = """BREAKING: Dr. A. Rao told reporters the Sector 9 bridge collapsed on Monday, 5 March 2024, and 47 people died.
Police said 12 people died in the collapse. Officials said 47 people died in the collapse.
Local news says the bridge collapsed on 7 March 2024. The state government paid Rs. 2.5 crore in compensation, while
the contractor did not pay any compensation. Turnout at the memorial was about 1,200 people.
I think this is a disgrace. Why is nobody talking about this? Share this now before it is deleted!!!"""


def test_realistic_post_end_to_end():
    report = analyze(REALISTIC_POST)
    assert [claim.kind for claim in report.claims].count("factual") == 8
    assert {claim.kind for claim in report.claims} == {"factual", "opinion", "question", "call_to_action"}
    assert not any(claim.text.endswith("while") for claim in report.claims)
    # "Sector 9" names a place. It does not count nine of anything.
    assert all(number.value != 9 for claim in report.claims for number in claim.numbers)

    flags = {(item.kind, item.severity) for item in report.inconsistencies}
    assert ("weekday_mismatch", "conflict") in flags
    assert ("dates", "note") in flags
    police_vs_officials = [
        item for item in report.inconsistencies if item.kind == "figures" and "police and officials" in item.explanation
    ]
    assert [item.severity for item in police_vs_officials] == ["note"]
    # The government paying and the contractor not paying are about different payers.
    assert "negation" not in {kind for kind, _ in flags}


def test_short_clause_with_a_figure_stands_alone():
    text = "The old railway bridge collapsed on Friday morning, and 47 people died."
    assert split_claims(text) == ["The old railway bridge collapsed on Friday morning", "47 people died."]


def test_wrapped_lines_join_but_real_lines_stay_apart():
    assert split_claims("The bridge fell\nnear the old station.") == ["The bridge fell near the old station."]
    assert split_claims("The bridge fell\nThe road closed") == ["The bridge fell", "The road closed"]


def test_flags_are_capped_and_the_cap_is_reported():
    text = " ".join(f"The factory fire killed {index} people." for index in range(1, 21))
    report = analyze(text)
    assert len(report.inconsistencies) == 25
    assert any("first 25 of 190" in item for item in report.limitations)


def test_claim_limit_is_reported_not_silent():
    text = " ".join(f"Statement number {index} was made." for index in range(25))
    report = analyze(text)
    assert len(report.claims) == 20
    assert report.omitted_claims == 5
    assert any("5 more were not" in item for item in report.limitations)
