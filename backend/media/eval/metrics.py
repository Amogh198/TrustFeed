"""Measures of detector results. Pure Python, with no model or file access."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

REAL = "real"
FAKE = "fake"
BANDS = ("elevated", "inconclusive", "low")
HISTOGRAM_BINS = 10
# Below this, an interval is too wide to support any claim about the class.
SMALL_SAMPLE = 30
_Z_95 = 1.959964


@dataclass(frozen=True)
class Scored:
    label: str
    score: float
    band: str
    category: str = "uncategorized"


def wilson_interval(successes: int, total: int) -> tuple[float, float] | None:
    """Return the 95% Wilson interval, which stays sensible at small counts and at 0 or 100%."""
    if total <= 0:
        return None
    rate = successes / total
    z2 = _Z_95**2
    denominator = 1 + z2 / total
    centre = (rate + z2 / (2 * total)) / denominator
    margin = _Z_95 * math.sqrt(rate * (1 - rate) / total + z2 / (4 * total**2)) / denominator
    # The exact bounds at 0 and at total, without rounding error.
    low = 0.0 if successes == 0 else max(0.0, centre - margin)
    high = 1.0 if successes == total else min(1.0, centre + margin)
    return round(low, 4), round(high, 4)


def proportion(successes: int, total: int) -> dict:
    interval = wilson_interval(successes, total)
    return {
        "count": successes,
        "total": total,
        "value": round(successes / total, 4) if total else None,
        "ci95": list(interval) if interval else None,
    }


def histogram(scores: Iterable[float]) -> list[int]:
    counts = [0] * HISTOGRAM_BINS
    for score in scores:
        counts[min(int(score * HISTOGRAM_BINS), HISTOGRAM_BINS - 1)] += 1
    return counts


def auc(items: Sequence[Scored]) -> float | None:
    """Chance a fake outscores a real image, with ties counted as half. None without both classes."""
    fakes = sorted(item.score for item in items if item.label == FAKE)
    reals = sorted(item.score for item in items if item.label == REAL)
    if not fakes or not reals:
        return None
    wins = 0.0
    below = same_end = 0
    for score in fakes:
        while below < len(reals) and reals[below] < score:
            below += 1
        same_end = max(same_end, below)
        while same_end < len(reals) and reals[same_end] == score:
            same_end += 1
        wins += below + (same_end - below) / 2
    return round(wins / (len(fakes) * len(reals)), 4)


def evaluate(items: Sequence[Scored]) -> dict:
    """Measure the detector's three-way bands.

    Inconclusive results count against recall, because they did not flag the fake. They
    are reported separately as well, so a detector cannot look good by rarely answering.
    """
    fakes = [item for item in items if item.label == FAKE]
    reals = [item for item in items if item.label == REAL]
    confusion = {
        label: {band: sum(item.band == band for item in group) for band in BANDS}
        for label, group in ((FAKE, fakes), (REAL, reals))
    }
    return {
        "n": {FAKE: len(fakes), REAL: len(reals)},
        "too_few_to_conclude": len(fakes) < SMALL_SAMPLE or len(reals) < SMALL_SAMPLE,
        "confusion": confusion,
        "recall": proportion(confusion[FAKE]["elevated"], len(fakes)),
        "false_positive_rate": proportion(confusion[REAL]["elevated"], len(reals)),
        "inconclusive_rate": proportion(confusion[FAKE]["inconclusive"] + confusion[REAL]["inconclusive"], len(items)),
        "auc": auc(items),
        "score_histogram": {
            "bin_width": 1 / HISTOGRAM_BINS,
            FAKE: histogram(item.score for item in fakes),
            REAL: histogram(item.score for item in reals),
        },
    }


def choose_threshold(items: Sequence[Scored], minimum_per_class: int = 10) -> tuple[float | None, str | None]:
    """Choose the cut-off with the best recall minus false positive rate.

    Ties go to the highest cut-off, which raises fewer false alarms. Returns the cut-off,
    or None and the reason there is too little data to choose one.
    """
    fakes = [item.score for item in items if item.label == FAKE]
    reals = [item.score for item in items if item.label == REAL]
    if len(fakes) < minimum_per_class or len(reals) < minimum_per_class:
        return None, (
            f"Needs at least {minimum_per_class} images of each class on the calibration split "
            f"(has {len(fakes)} fake and {len(reals)} real)."
        )
    best_value = -2.0
    best_cut = 1.0
    for cut in sorted({*fakes, *reals}, reverse=True):
        value = sum(s >= cut for s in fakes) / len(fakes) - sum(s >= cut for s in reals) / len(reals)
        if value > best_value:
            best_value = value
            best_cut = cut
    return best_cut, None


def at_threshold(items: Sequence[Scored], cut: float) -> dict:
    """Measure a single cut-off. There is no inconclusive band here."""
    fakes = [item for item in items if item.label == FAKE]
    reals = [item for item in items if item.label == REAL]
    return {
        "n": {FAKE: len(fakes), REAL: len(reals)},
        "too_few_to_conclude": len(fakes) < SMALL_SAMPLE or len(reals) < SMALL_SAMPLE,
        "recall": proportion(sum(item.score >= cut for item in fakes), len(fakes)),
        "false_positive_rate": proportion(sum(item.score >= cut for item in reals), len(reals)),
    }
