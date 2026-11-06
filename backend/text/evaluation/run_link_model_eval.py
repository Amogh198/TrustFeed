"""Measure the phishing model on link addresses, without opening any.

    python -m backend.text.evaluation.run_link_model_eval --write

Phishing addresses come live from OpenPhish and aren't saved. Ordinary addresses are the same
50 famous sites as run_link_feed_eval, which is a small, easy set.
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path

from backend.provenance.safe_http import safe_request
from backend.text.evaluation.run_link_feed_eval import ORDINARY
from backend.text.links import THREAT_FEEDS
from backend.text.scam_model import MODEL_ID, MODEL_REVISION, HuggingFacePhishing


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    body = safe_request(THREAT_FEEDS["OpenPhish"], max_bytes=5_000_000, max_redirects=2, headers={"User-Agent": "TrustFeed-LinkCheck/1.0"}).body
    phish = [line.strip() for line in body.decode("utf-8", "replace").splitlines() if line.startswith("http")][:300]
    ordinary = [f"https://www.{site}/" for site in ORDINARY]
    model = HuggingFacePhishing()
    phish_scores, ordinary_scores = model.predict(phish), model.predict(ordinary)
    rows = {
        str(line): {
            "phishing_flagged": f"{sum(s >= line for s in phish_scores)} of {len(phish_scores)}",
            "ordinary_flagged": f"{sum(s >= line for s in ordinary_scores)} of {len(ordinary_scores)}",
        }
        for line in (0.3, 0.5, 0.7, 0.9, 0.99)
    }
    result = {
        "measured_on": datetime.now(UTC).date().isoformat(),
        "model": MODEL_ID,
        "revision": MODEL_REVISION,
        "median_score_phishing": round(statistics.median(phish_scores), 4),
        "median_score_ordinary": round(statistics.median(ordinary_scores), 4),
        "by_line": rows,
        "caveats": ["Ordinary addresses are 50 famous home pages, far easier than typical traffic.", "No page was opened. This scores the address text alone."],
    }
    print(json.dumps(result, indent=1))
    if args.write:
        (Path(__file__).parent / "results" / "link_model_eval.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
