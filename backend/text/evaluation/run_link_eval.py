"""Measure the offline lookalike check on hand-written addresses.

    python -m backend.text.evaluation.run_link_eval --split dev
    python -m backend.text.evaluation.run_link_eval --split test --write

Tune only on ``dev``. Any figure quoted elsewhere must come from the written results file.
This measures the address check alone: no page was opened and no registry was asked.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from backend.text.links import investigate_link

HERE = Path(__file__).parent
CAVEATS = [
    "All addresses are hand-written by the author of the rules, so these figures are likely too high for real phishing.",
    "The imitations mostly target the 14 listed brands. Real phishing often imitates others, which this check can't recognise.",
    "Imitations are about half of this set, far more than in real traffic, so precision here overstates real precision.",
    "The set is small, so one address moves a figure by several points.",
    "Redirects, domain age, page content and official-site comparison are not measured here.",
    "The rules were widened on 2026-11-06 after reading this test split's misses, so the test split is no longer held out and its figures are likely too high.",
]


def measure(split: str) -> dict:
    rows = [json.loads(line) for line in (HERE / "link_examples.jsonl").read_text(encoding="utf-8").splitlines() if line]
    tp = fp = fn = tn = 0
    errors = []
    for row in rows:
        if row["split"] != split:
            continue
        assessment = investigate_link(row["url"], offline_reason="Evaluation stays offline.").assessment
        flagged = assessment == "warning_signs_found"
        imitation = row["label"] == "imitation"
        tp += flagged and imitation
        fp += flagged and not imitation
        fn += imitation and not flagged
        tn += not imitation and not flagged
        if flagged != imitation:
            errors.append({"url": row["url"], "label": row["label"], "assessment": assessment})
    return {
        "split": split,
        "measured_on": datetime.now(UTC).date().isoformat(),
        "check": "offline address check only (warning_signs_found counts as flagged)",
        "imitations_flagged": f"{tp} of {tp + fn}",
        "ordinary_flagged": f"{fp} of {fp + tn}",
        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "errors": errors,
        "caveats": CAVEATS,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "test"), required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    result = measure(args.split)
    print(json.dumps(result, indent=2))
    if args.write:
        (HERE / "results" / f"link_eval_{args.split}.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
