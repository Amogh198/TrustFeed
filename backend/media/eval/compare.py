"""Compare detectors on the same images. Pure Python, with no model or file access.

Anything that could be tuned is chosen on the calibration split and measured on the test split.
"""

from __future__ import annotations

import random
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations

from backend.media.eval.metrics import FAKE, REAL, SMALL_SAMPLE, Scored, at_threshold, auc

BOOTSTRAP_SAMPLES = 1000
TARGET_FALSE_ALARM_RATE = 0.05
_LOW, _HIGH = 2.5, 97.5
METHOD = (
    "Intervals resample the test images 1000 times within each class, using the same images for both detectors. "
    "A detector or combination adds value only if the whole 95% interval of its AUC difference from the baseline is "
    "above zero. Thresholds and combination members are chosen on the calibration split."
)


@dataclass(frozen=True)
class Row:
    """One image, with a score from every compared model."""

    label: str
    category: str
    split: str
    scores: tuple[float, ...]


def _column(rows: Sequence[Row], index: int) -> list[Scored]:
    return [Scored(row.label, row.scores[index], "", row.category) for row in rows]


def _percentile(values: Sequence[float], percent: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _resamples(items: Sequence[Scored], seed: int, samples: int) -> list[list[int]]:
    """Index lists that keep each class's size, so every resample has both classes."""
    generator = random.Random(seed)
    groups = [[i for i, item in enumerate(items) if item.label == label] for label in (FAKE, REAL)]
    return [[index for group in groups for index in generator.choices(group, k=len(group))] for _ in range(samples)]


def auc_with_interval(items: Sequence[Scored], seed: int = 0, samples: int = BOOTSTRAP_SAMPLES) -> dict:
    point = auc(items)
    if point is None:
        return {"auc": None, "ci95": None}
    values = [auc([items[i] for i in chosen]) for chosen in _resamples(items, seed, samples)]
    return {"auc": point, "ci95": [round(_percentile(values, _LOW), 4), round(_percentile(values, _HIGH), 4)]}


def difference_from_baseline(
    items: Sequence[Scored], baseline: Sequence[Scored], seed: int = 0, samples: int = BOOTSTRAP_SAMPLES
) -> dict:
    """AUC of items minus AUC of baseline, resampling the same images for both."""
    first, second = auc(items), auc(baseline)
    if first is None or second is None:
        return {"difference": None, "ci95": None, "adds_value": False}
    values = [
        auc([items[i] for i in chosen]) - auc([baseline[i] for i in chosen])
        for chosen in _resamples(items, seed, samples)
    ]
    low, high = round(_percentile(values, _LOW), 4), round(_percentile(values, _HIGH), 4)
    return {"difference": round(first - second, 4), "ci95": [low, high], "adds_value": low > 0}


def cut_for_false_alarm_rate(calibration: Sequence[Scored], target: float = TARGET_FALSE_ALARM_RATE) -> float | None:
    """The lowest cut-off that flags at most the target share of real calibration images."""
    reals = sorted((item.score for item in calibration if item.label == REAL), reverse=True)
    if len(reals) < SMALL_SAMPLE:
        return None
    allowed = int(len(reals) * target)
    # Scores equal to the cut-off are flagged, so step just above the first real image not allowed through.
    return min(1.0, reals[allowed] + 1e-9)


def contrasts(test: Sequence[Scored]) -> dict[str, dict]:
    """AUC for each kind of fake against each kind of real, since a detector can react to subject matter."""
    fakes = sorted({item.category for item in test if item.label == FAKE})
    reals = sorted({item.category for item in test if item.label == REAL})
    result = {}
    for fake in fakes:
        for real in reals:
            chosen = [
                item
                for item in test
                if (item.label == FAKE and item.category == fake) or (item.label == REAL and item.category == real)
            ]
            n_fake = sum(item.label == FAKE for item in chosen)
            n_real = len(chosen) - n_fake
            result[f"{fake} vs {real}"] = {
                "auc": auc(chosen),
                "n": {FAKE: n_fake, REAL: n_real},
                "too_few_to_conclude": n_fake < SMALL_SAMPLE or n_real < SMALL_SAMPLE,
            }
    return result


def _rank_maps(calibration: Sequence[Row], width: int) -> list[list[float]]:
    return [sorted(row.scores[index] for row in calibration) for index in range(width)]


def _combined(rows: Sequence[Row], members: Sequence[int], ranks: Sequence[list[float]]) -> list[Scored]:
    """Average each member's position among its calibration scores, because raw scores aren't comparable."""
    result = []
    for row in rows:
        values = [bisect_right(ranks[m], row.scores[m]) / max(1, len(ranks[m])) for m in members]
        result.append(Scored(row.label, sum(values) / len(values), "", row.category))
    return result


def best_combination(rows: Sequence[Row], names: Sequence[str], baseline_index: int, seed: int = 0) -> dict | None:
    """Choose the best average of detectors on calibration images, then measure it once on test images."""
    calibration = [row for row in rows if row.split == "calibration"]
    test = [row for row in rows if row.split == "test"]
    if len(names) < 2 or not calibration or not test:
        return None
    ranks = _rank_maps(calibration, len(names))
    best: tuple[float, tuple[int, ...]] | None = None
    for size in range(2, len(names) + 1):
        for members in combinations(range(len(names)), size):
            value = auc(_combined(calibration, members, ranks))
            if value is None:
                return None
            # Ties keep the smaller combination, because sizes run upwards.
            if best is None or value > best[0]:
                best = (value, members)
    assert best is not None
    combined_test = _combined(test, best[1], ranks)
    return {
        "members": [names[m] for m in best[1]],
        "chosen_on": "calibration split",
        "calibration_auc": best[0],
        "test_split": {
            **auc_with_interval(combined_test, seed),
            "difference_from_baseline": difference_from_baseline(combined_test, _column(test, baseline_index), seed),
        },
    }


def compare_models(
    scores_by_model: Mapping[str, Mapping[str, tuple[str, str, str, float]]],
    baseline: str,
    *,
    seed: int = 0,
    seconds_per_image: Mapping[str, float | None] | None = None,
) -> dict:
    """Compare models on the images all of them scored.

    Each model maps an image key to (label, category, split, score).
    """
    names = list(scores_by_model)
    shared = set.intersection(*(set(values) for values in scores_by_model.values()))
    rows = [
        Row(*scores_by_model[baseline][key][:3], tuple(scores_by_model[name][key][3] for name in names))
        for key in sorted(shared)
    ]
    test = [row for row in rows if row.split == "test"]
    calibration = [row for row in rows if row.split == "calibration"]
    baseline_index = names.index(baseline)
    baseline_test = _column(test, baseline_index)
    models = []
    for index, name in enumerate(names):
        model_test = _column(test, index)
        cut = cut_for_false_alarm_rate(_column(calibration, index))
        models.append(
            {
                "model": name,
                "test_split": auc_with_interval(model_test, seed),
                "difference_from_baseline": None
                if name == baseline
                else difference_from_baseline(model_test, baseline_test, seed),
                "at_low_false_alarm_rate": {
                    "target_on_calibration": TARGET_FALSE_ALARM_RATE,
                    "threshold": round(cut, 6) if cut is not None else None,
                    "test_split": at_threshold(model_test, cut) if cut is not None else None,
                },
                "contrasts_on_test_split": contrasts(model_test),
                "seconds_per_image": (seconds_per_image or {}).get(name),
            }
        )
    return {
        "baseline": baseline,
        "images_scored_by_every_model": len(rows),
        "method": METHOD,
        "models": models,
        "combination": best_combination(rows, names, baseline_index, seed),
        "limitations": [
            "Several detectors are compared on one set of images, so one could look better by chance.",
            "A difference measured here does not show the detector would do better on other kinds of image.",
        ],
    }
