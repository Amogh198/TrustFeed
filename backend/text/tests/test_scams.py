"""Scam rules, and the checks that keep the published figures honest. No model is needed."""

import json
import threading
from pathlib import Path

import pytest

from backend.text.claims import split_claims
from backend.text.evaluation import run_scam_eval
from backend.text.scam_model import PhishingRunner, PhishingUnavailable
from backend.text.scams import NONE_FOUND, WARNING_SIGNS, WEAK_ONLY, find_signs

RESULTS = Path(run_scam_eval.__file__).parent / "results"
SPLITS = ("dev", "test")


def signs_of(text):
    return {item.sign for item in find_signs(text).signs}


@pytest.mark.parametrize(
    ("text", "sign", "category"),
    [
        ("Pay Rs 1500 registration fee to get your offer letter for this job.", "job_upfront_fee", "fake_job"),
        ("Invest now for guaranteed returns of 30%.", "guaranteed_returns", "investment"),
        ("Double your money in 7 days.", "money_multiplier", "investment"),
        ("You have won a phone! Claim your prize now.", "you_won", "giveaway"),
        ("You are under digital arrest. Do not disconnect.", "official_threat", "impersonation"),
        ("Your account will be blocked today. Click the link to update it.", "account_threat", "impersonation"),
        ("Buy 5 gift cards and send me the codes.", "gift_card_payment", "payment_request"),
        ("Reply with the OTP we just sent you.", "credential_request", "credential_request"),
        ("कृपया अपना ओटीपी भेजें।", "credential_request_hindi", "credential_request"),
    ],
)
def test_each_kind_of_scam_is_named_with_a_reason_and_a_quote(text, sign, category):
    report = find_signs(text)
    found = next(item for item in report.signs if item.sign == sign)
    assert found.category == category
    assert found.why
    assert found.quote and found.quote.casefold() in text.casefold()
    assert report.assessment == WARNING_SIGNS


@pytest.mark.parametrize(
    "text",
    [
        "Never share your OTP with anyone.",
        "Your OTP is 482910. Do not share it with anyone.",
        "Police warned that scammers ask people to pay a registration fee for fake jobs.",
        "The regulator warned against schemes offering guaranteed returns.",
        "India has won the final by six wickets.",
        "We are hiring an engineer. Apply on our careers page.",
        "To reset your password, open Settings and follow the steps.",
        "The index fund returned 12% last year.",
        "Share prices fell 5% today.",
    ],
)
def test_the_same_words_in_a_warning_or_ordinary_post_are_not_signs(text):
    assert find_signs(text).assessment == NONE_FOUND


@pytest.mark.parametrize(
    "text",
    [
        "This is not a scam, send your OTP now.",
        "Scammers are everywhere. Reply with the OTP we sent you.",
        "Do not delay, send your password today.",
        "Enter your password in settings and send it to us.",
        "किसी को मत बताना, अपना पिन भेजें।",
        "नहीं तो खाता बंद होगा, अपना ओटीपी भेजें।",
    ],
)
def test_a_scammer_cannot_switch_off_the_rules_with_a_few_words(text):
    assert find_signs(text).assessment == WARNING_SIGNS


def test_real_hindi_warning_is_still_not_a_sign():
    assert find_signs("अपना ओटीपी किसी को न भेजें।").assessment == NONE_FOUND


def test_one_weak_sign_alone_is_not_a_warning():
    report = find_signs("Our new hiring process has no interview.")
    assert report.assessment == WEAK_ONLY
    assert [item.sign for item in report.signs] == ["job_no_checks"]


def test_two_weak_signs_together_are_a_warning():
    report = find_signs("Part time job with no interview. Talk to us on Telegram.")
    assert report.assessment == WARNING_SIGNS


def test_no_quote_runs_on_forever():
    text = "Reply with the " + "x" * 25 + " OTP. " + "y" * 500
    assert all(len(item.quote) <= 120 for item in find_signs(text).signs)


@pytest.mark.parametrize(
    "text",
    ["pay " * 5000, "send your " * 2000, "a" * 20000, "1," * 10000, "account " * 2500, "free " * 4000, "transfer usdt " * 1500],
)
def test_long_hostile_input_finishes_quickly(text):
    finished = threading.Event()
    threading.Thread(target=lambda: (find_signs(text), finished.set()), daemon=True).start()
    assert finished.wait(5), "The rules took too long on hostile input"


# The published figures


@pytest.mark.parametrize("split", SPLITS)
def test_results_files_match_what_the_rules_do_today(split):
    saved = json.loads((RESULTS / f"scam_eval_{split}.json").read_text(encoding="utf-8"))["rules"]
    rows = run_scam_eval.load(split)
    flagged = {row["id"]: find_signs(row["text"]).assessment != NONE_FOUND for row in rows}
    current = run_scam_eval._metrics(rows, flagged)
    assert {key: saved[key] for key in current} == current


@pytest.mark.parametrize("split", SPLITS)
def test_results_files_state_their_limits(split):
    saved = json.loads((RESULTS / f"scam_eval_{split}.json").read_text(encoding="utf-8"))
    assert any("not independent" in item for item in saved["caveats"])
    assert saved["model"]["revision"]


@pytest.mark.parametrize("split", SPLITS)
def test_the_api_path_gives_the_same_flags_as_the_measured_path(split):
    # The API sees the post after claim splitting, so the figures must hold for that form too.
    for row in run_scam_eval.load(split):
        direct = find_signs(row["text"]).assessment != NONE_FOUND
        through_claims = find_signs("\n".join(split_claims(row["text"]))).assessment != NONE_FOUND
        assert direct == through_claims, row["id"]


def test_examples_are_balanced_and_have_unique_ids():
    rows = [row for split in SPLITS for row in run_scam_eval.load(split)]
    assert len({row["id"] for row in rows}) == len(rows)
    for split in SPLITS:
        labels = [row["label"] for row in run_scam_eval.load(split)]
        assert labels.count("scam") == labels.count("legit")


# The model is optional


class Backend:
    def __init__(self, reason=None, score=0.9, error=None, release=None):
        self.reason, self.score, self.error, self.release = reason, score, error, release

    def is_ready(self):
        return self.reason

    def predict(self, texts):
        if self.release is not None:
            self.release.wait(10)
        if self.error is not None:
            raise self.error
        return [self.score for _ in texts]


def test_runner_returns_a_score():
    outcome = PhishingRunner(Backend(score=0.42)).run("text")
    assert (outcome.status, outcome.score) == ("complete", 0.42)


def test_runner_reports_a_missing_model():
    outcome = PhishingRunner(Backend(reason="Not downloaded.")).run("text")
    assert (outcome.status, outcome.reason, outcome.score) == ("unavailable", "Not downloaded.", None)


def test_runner_keeps_content_out_of_failures(caplog):
    outcome = PhishingRunner(Backend(error=ValueError("the submitted text"))).run("the submitted text")
    assert outcome.status == "unavailable"
    assert "the submitted text" not in (outcome.reason or "")
    assert "the submitted text" not in caplog.text
    known = PhishingRunner(Backend(error=PhishingUnavailable("Packages are missing."))).run("text")
    assert known.reason == "Packages are missing."


def test_runner_has_a_time_limit_and_does_not_pile_up():
    release = threading.Event()
    runner = PhishingRunner(Backend(release=release), timeout_seconds=0.05)
    assert "did not finish within" in (runner.run("text").reason or "")
    assert "busy" in (runner.run("text").reason or "")
    release.set()
