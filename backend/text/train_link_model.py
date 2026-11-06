"""Train the link model: logistic regression on hashed letter sequences from a host name.

    python -m backend.text.train_link_model

Phishing hosts come from Phishing.Database (MIT), popular sites from the Tranco list. Whole
registered domains are held out for testing, so the test figures are on domains it never saw.
The lists aren't saved, only the weights in link_model.npz and results/link_model_train.json.
"""

from __future__ import annotations

import io
import json
import random
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from backend.provenance.safe_http import safe_request
from backend.text.analysis import _registered_domain
from backend.text.evaluation.run_link_feed_eval import ORDINARY
from backend.text.link_model import MODEL_PATH, SIZE, features
from backend.text.links import THREAT_FEEDS

TRANCO = "https://tranco-list.eu/top-1m.csv.zip"
HEADERS = {"User-Agent": "TrustFeed-LinkCheck/1.0"}
PER_CLASS = 150_000
EPOCHS = 4
RESULTS = Path(__file__).parent / "evaluation" / "results" / "link_model_train.json"


def _read(url: str) -> bytes:
    return safe_request(url, headers=HEADERS, timeout_s=30.0, max_bytes=80 * 1024 * 1024, max_redirects=3).body


def _auc(positive: list[float], negative: list[float]) -> float:
    scores = np.array(positive + negative)
    ranks = np.empty(len(scores))
    ranks[scores.argsort()] = np.arange(1, len(scores) + 1)
    return float((ranks[: len(positive)].sum() - len(positive) * (len(positive) + 1) / 2) / (len(positive) * len(negative)))


def main() -> None:
    rng = random.Random(42)
    phish = sorted({line.strip().casefold() for line in _read(THREAT_FEEDS["Phishing.Database"]).decode("utf-8", "replace").splitlines() if line.strip() and not line.startswith("#")})
    with zipfile.ZipFile(io.BytesIO(_read(TRANCO))) as archive:
        rows = archive.read(archive.namelist()[0]).decode("utf-8", "replace").splitlines()
    ordinary = [row.split(",", 1)[1].strip().casefold() for row in rows if "," in row]
    famous = set(ORDINARY)
    ordinary = [host for host in ordinary if host not in famous]
    known_bad = set(phish)
    ordinary = [host for host in ordinary if host not in known_bad]
    rng.shuffle(phish)
    # Popular first, as the far end of the list holds abused domains too.
    ordinary = ordinary[:PER_CLASS * 2]
    rng.shuffle(ordinary)
    phish, ordinary = phish[:PER_CLASS], ordinary[:PER_CLASS]

    def is_test(host: str) -> bool:
        return hash_domain(_registered_domain(host)) % 5 == 0

    def hash_domain(domain: str) -> int:
        return sum(domain.encode())  # Stable between runs, and enough to split domains.

    train = [(host, 1) for host in phish if not is_test(host)] + [(host, 0) for host in ordinary if not is_test(host)]
    test_phish = [host for host in phish if is_test(host)]
    test_ordinary = [host for host in ordinary if is_test(host)]
    rng.shuffle(train)

    weights = [0.0] * SIZE
    bias = 0.0
    prepared = [(features(host), label) for host, label in train]
    for epoch in range(EPOCHS):
        rate = 0.5 / (1 + epoch)
        for items, label in prepared:
            if not items:
                continue
            value = 1.0 / len(items) ** 0.5
            margin = bias + sum(weights[i] for i in items) * value
            error = label - 1.0 / (1.0 + np.exp(-max(-30.0, min(30.0, margin))))
            step = rate * error * value
            for i in items:
                weights[i] += step
            bias += rate * error * 0.1
    array = np.array(weights, dtype=np.float32)
    np.savez_compressed(MODEL_PATH, weights=array, bias=np.array([bias], dtype=np.float32))

    from backend.text.link_model import reset, score_host

    reset()
    scores_phish = [score_host(host) for host in test_phish]
    scores_ordinary = [score_host(host) for host in test_ordinary]
    famous_scores = {site: score_host(f"www.{site}") for site in ORDINARY}
    lines = {}
    for line in (0.5, 0.7, 0.8, 0.9, 0.95):
        caught = sum(score >= line for score in scores_phish)
        wrong = sum(score >= line for score in scores_ordinary)
        lines[str(line)] = {
            "phishing_flagged": round(caught / len(scores_phish), 4),
            "ordinary_flagged": round(wrong / len(scores_ordinary), 4),
            "accuracy": round((caught + len(scores_ordinary) - wrong) / (len(scores_phish) + len(scores_ordinary)), 4),
            "famous_flagged": sum(score >= line for score in famous_scores.values()),
        }
    result = {
        "trained_on": datetime.now(UTC).date().isoformat(),
        "train_hosts": len(train),
        "test_phishing_hosts": len(scores_phish),
        "test_ordinary_hosts": len(scores_ordinary),
        "auc": round(_auc(scores_phish, scores_ordinary), 4),
        "by_line": lines,
        "famous_sites_median_score": round(float(np.median(list(famous_scores.values()))), 4),
        "famous_sites_highest": sorted(famous_scores.items(), key=lambda item: -item[1])[:5],
        "caveats": [
            "Reads the host name only. It doesn't open pages or see the path.",
            "Half of the test set is phishing, far more than in real traffic, so accuracy here overstates real use.",
            "Ordinary hosts come from a popularity list, so small genuine sites may score higher than these figures suggest.",
            "Held-out domains are from the same lists, so new phishing styles may do worse.",
        ],
    }
    RESULTS.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
