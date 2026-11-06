"""Measure the scam rules and the phishing model on the hand-written labelled examples.

    python -m backend.text.evaluation.run_scam_eval --split dev
    python -m backend.text.evaluation.run_scam_eval --split test --write

Tune only on ``dev``. ``test`` is held out, so run it once after tuning has stopped.
With ``--write``, the results go to ``results/scam_eval_<split>.json``. Any accuracy
figure quoted elsewhere must come from one of those files.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from backend.text.scam_model import (
    LABEL_NAMES,
    MODEL_ID,
    MODEL_REVISION,
    PHISHING_THRESHOLD,
    HuggingFacePhishing,
)
from backend.text.scams import NONE_FOUND, WEAK_ONLY, find_signs

HERE = Path(__file__).parent
EXAMPLES = HERE / "scam_examples.jsonl"
RESULTS = HERE / "results"
CAVEATS = [
    "All examples are synthetic, hand-written and in English apart from two in Hindi.",
    ("The same author wrote the rules and both splits, just before the rules, so even the test split is not independent. "
    "These figures are likely too high for real messages."),
    ("The rules were frozen in commit ddebf63 before the test split was first scored, then changed once after "
    "it, to close bypasses a security review found. So these figures are not a pure first score."),
    "The set is small, so one example moves a figure by several points.",
    "Scams are half of this set, which is far more than in real feeds, so precision here overstates real precision.",
]


def load(split: str) -> list[dict[str, str]]:
    rows = [json.loads(line) for line in EXAMPLES.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [row for row in rows if row["split"] == split]


def _metrics(rows: list[dict[str, str]], flagged: dict[str, bool]) -> dict[str, object]:
    tp = sum(row["label"] == "scam" and flagged[row["id"]] for row in rows)
    fp = sum(row["label"] == "legit" and flagged[row["id"]] for row in rows)
    fn = sum(row["label"] == "scam" and not flagged[row["id"]] for row in rows)
    tn = sum(row["label"] == "legit" and not flagged[row["id"]] for row in rows)
    return {
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "true_negative": tn,
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "false_positive_rate": round(fp / (fp + tn), 3) if fp + tn else None,
        "missed": [row["id"] for row in rows if row["label"] == "scam" and not flagged[row["id"]]],
        "false_alarms": [row["id"] for row in rows if row["label"] == "legit" and flagged[row["id"]]],
    }


def _by_category(rows: list[dict[str, str]], flagged: dict[str, bool]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for row in rows:
        entry = summary.setdefault(row["category"], {"examples": 0, "flagged": 0})
        entry["examples"] += 1
        entry["flagged"] += int(flagged[row["id"]])
    return summary


def evaluate(split: str) -> dict[str, object]:
    rows = load(split)
    reports = {row["id"]: find_signs(row["text"]) for row in rows}
    rules = {row_id: report.assessment != NONE_FOUND for row_id, report in reports.items()}

    model = HuggingFacePhishing()
    reason = model.is_ready()
    results: dict[str, object] = {
        "split": split,
        "examples": len(rows),
        "scams": sum(row["label"] == "scam" for row in rows),
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "caveats": CAVEATS,
        "rules": {
            **_metrics(rows, rules),
            "by_category": _by_category(rows, rules),
            # A flag for the wrong reason would name the wrong warning sign to the user.
            "scams_given_the_right_category": sum(
                row["label"] == "scam" and row["category"] in reports[row["id"]].categories for row in rows
            ),
            "scams_flagged_only_by_weak_signs": sum(
                row["label"] == "scam" and reports[row["id"]].assessment == WEAK_ONLY for row in rows
            ),
            "scams_given_a_different_category": {
                row["id"]: reports[row["id"]].categories
                for row in rows
                if row["label"] == "scam" and reports[row["id"]].signs and row["category"] not in reports[row["id"]].categories
            },
        },
    }
    if reason:
        results["model"] = {"status": "unavailable", "reason": reason}
        return results

    probabilities = model.probabilities([row["text"] for row in rows])
    scores = {
        row["id"]: round(probs[1] + probs[3], 4) for row, probs in zip(rows, probabilities, strict=True)
    }
    # The model's config names no labels, so show what each one really fires on.
    winners: dict[str, dict[str, int]] = {"scam": dict.fromkeys(LABEL_NAMES, 0), "legit": dict.fromkeys(LABEL_NAMES, 0)}
    for row, probs in zip(rows, probabilities, strict=True):
        winners[row["label"]][LABEL_NAMES[probs.index(max(probs))]] += 1
    scam_count = sum(row["label"] == "scam" for row in rows)
    phishing = {row_id: score >= PHISHING_THRESHOLD for row_id, score in scores.items()}
    results["model"] = {
        "status": "complete",
        "model_id": MODEL_ID,
        "revision": MODEL_REVISION,
        "threshold": PHISHING_THRESHOLD,
        **_metrics(rows, phishing),
        "by_category": _by_category(rows, phishing),
        "mean_score_scam": round(sum(scores[r["id"]] for r in rows if r["label"] == "scam") / max(1, scam_count), 3),
        "mean_score_legit": round(sum(scores[r["id"]] for r in rows if r["label"] == "legit") / max(1, len(rows) - scam_count), 3),
        "top_label_counts": winners,
    }
    results["rules_or_model"] = _metrics(rows, {row_id: rules[row_id] or phishing[row_id] for row_id in rules})
    results["rules_and_model"] = _metrics(rows, {row_id: rules[row_id] and phishing[row_id] for row_id in rules})
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument("--write", action="store_true", help="save the results file")
    args = parser.parse_args()
    results = evaluate(args.split)
    print(json.dumps(results, indent=1, ensure_ascii=False))
    if args.write:
        RESULTS.mkdir(exist_ok=True)
        (RESULTS / f"scam_eval_{args.split}.json").write_text(
            json.dumps(results, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
