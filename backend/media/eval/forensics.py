"""Measure each pixel forensics test, and say plainly if it adds nothing.

    python -m backend.media.eval.forensics --real DIR --fake DIR --out data/eval/RESULT.json \
        --source "name|licence|url" [--detector-cache DIR]

Limits are chosen on the calibration split and everything else is measured on the test split. Most of the AI-generated
images are PNG and most real ones are JPEG, so a test that reads compression could look good by only spotting the file
type. So each test is measured on the files as they are, on JPEG files only, and after re-saving every image the same
way. Spliced copies are made in memory and never written. The results hold only counts, never images or file names.
"""

from __future__ import annotations

import argparse
import io
import sys
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image

from backend.media.config import MediaConfig
from backend.media.eval.metrics import FAKE, REAL, Scored, auc, proportion
from backend.media.eval.runner import Item, ScoreCache, build_dataset, parse_source
from backend.media.forensics import (
    COMPRESSION_GHOST,
    ELA,
    JPEG_ONLY,
    MAX_PIXELS,
    NOISE_UNEVENNESS,
    TEST_NAMES,
    Measurement,
    find_regions,
    measure_all,
)

SCHEMA = "forensics-eval-1"
_REGION_TESTS = frozenset({ELA, NOISE_UNEVENNESS, COMPRESSION_GHOST})
# The share of real images on the calibration split that each test's limit is set to flag.
TARGET_REAL_FLAGGED = 0.05
AI_GENERATED = "ai_generated"
EDITED = "edited"
RESAVE_SIDE = 1024
RESAVE_QUALITY = 90
LOW_RESAVE_QUALITY = 60
BOOTSTRAP_ROUNDS = 1000
# A test counts as separating two groups only if the AUC reaches this and its 95% interval stays above guessing.
USEFUL_AUC = 0.6
PATCH_FRACTION = 4
# A found region counts as a hit if it covers this share of the pasted patch, and isn't far larger than the patch.
HIT_COVERAGE = 0.5
HIT_MAX_AREA_RATIO = 4.0
NOTICE = (
    "Measured on the listed images and these simulated splices only. A test's score is a signal, not proof. An unusual "
    "reading can come from ordinary editing, and a normal reading doesn't show that an image is genuine."
)
LIMITATIONS = (
    "Splices were simulated with rectangular patches, without the blending a careful editor would use. Real edits are "
    "likely to be harder to find.",
    "Whole-image figures describe this collection. Commons images were often resized or re-saved before upload, and "
    "the 'edited' group holds many kinds of edit, most of which may not be local.",
    "Images larger than 3.3 megapixels, and images re-saved by real social media platforms, were not measured.",
    "Limits were set on real images from this collection, so false alarms elsewhere may be higher.",
    "Labels are as stated by whoever ran this measurement. The tool does not check them.",
)


def _resaved(image: Image.Image, *, quality: int = RESAVE_QUALITY, shrink: bool = True) -> Image.Image:
    copy = image.copy()
    if shrink:
        copy.thumbnail((RESAVE_SIDE, RESAVE_SIDE), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    copy.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    with Image.open(buffer) as reopened:
        return reopened.convert("RGB")


def _patch_box(image: Image.Image, position: int) -> tuple[int, int, int, int]:
    width, height = image.width // PATCH_FRACTION, image.height // PATCH_FRACTION
    generator = np.random.default_rng(position)
    left = int(generator.integers(0, image.width - width + 1))
    top = int(generator.integers(0, image.height - height + 1))
    return left, top, left + width, top + height


def _donor_patch(donor: Image.Image, size: tuple[int, int]) -> Image.Image:
    return donor.resize(size, Image.Resampling.LANCZOS)


def _paste_other_compression(image: Image.Image, donor: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    copy = image.copy()
    copy.paste(_resaved(_donor_patch(donor, (box[2] - box[0], box[3] - box[1])), quality=50, shrink=False), box[:2])
    return copy


def _paste_resampled(image: Image.Image, donor: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    copy = image.copy()
    width, height = box[2] - box[0], box[3] - box[1]
    small = _donor_patch(donor, (max(1, width // 2), max(1, height // 2)))
    copy.paste(small.resize((width, height), Image.Resampling.BILINEAR), box[:2])
    return copy


def _paste_noisy(image: Image.Image, donor: Image.Image, box: tuple[int, int, int, int]) -> Image.Image:
    copy = image.copy()
    width, height = box[2] - box[0], box[3] - box[1]
    patch = np.asarray(_donor_patch(donor, (width, height)), dtype=np.float32)
    noise = np.random.default_rng(width * height).normal(0, 8, patch.shape)
    copy.paste(Image.fromarray(np.clip(patch + noise, 0, 255).astype(np.uint8)), box[:2])
    return copy


SPLICES: dict[str, tuple[Callable[..., Image.Image], int]] = {
    "patch_saved_at_low_quality": (_paste_other_compression, RESAVE_QUALITY),
    "patch_upscaled": (_paste_resampled, RESAVE_QUALITY),
    "patch_with_added_noise": (_paste_noisy, RESAVE_QUALITY),
    "patch_saved_at_low_quality_then_all_re_saved_at_60": (_paste_other_compression, LOW_RESAVE_QUALITY),
}


def _scores(image: Image.Image) -> dict[str, Measurement]:
    return measure_all(np.asarray(image, dtype=np.uint8))


def auc_with_interval(fakes: Sequence[float], reals: Sequence[float], *, seed: int = 0) -> dict:
    """The AUC with a 95% bootstrap interval. Above 0.5, the group's scores run higher than real images'."""
    if not fakes or not reals:
        return {"auc": None, "ci95": None, "n": {FAKE: len(fakes), REAL: len(reals)}}
    point = auc([Scored(FAKE, value, "") for value in fakes] + [Scored(REAL, value, "") for value in reals])
    generator = np.random.default_rng(seed)
    fake_array, real_array = np.asarray(fakes), np.asarray(reals)
    rounds = []
    for _ in range(BOOTSTRAP_ROUNDS):
        fake_sample = generator.choice(fake_array, fake_array.size)
        real_sample = np.sort(generator.choice(real_array, real_array.size))
        below = np.searchsorted(real_sample, fake_sample, side="left")
        through = np.searchsorted(real_sample, fake_sample, side="right")
        rounds.append(float(np.mean((below + through) / 2) / real_sample.size))
    low, high = np.percentile(rounds, [2.5, 97.5])
    return {"auc": point, "ci95": [round(float(low), 4), round(float(high), 4)], "n": {FAKE: len(fakes), REAL: len(reals)}}


def separates(entry: dict) -> bool:
    return entry["auc"] is not None and entry["auc"] >= USEFUL_AUC and entry["ci95"][0] > 0.5


def choose_limit(real_scores: Sequence[float], target: float = TARGET_REAL_FLAGGED) -> float | None:
    """The score that the top share of real images reach."""
    if not real_scores:
        return None
    return round(float(np.quantile(np.asarray(real_scores), 1 - target, method="higher")), 4)


def _region_hit(measurement: Measurement, box: tuple[int, int, int, int]) -> bool:
    if measurement.block_z is None:
        return False
    patch_area = (box[2] - box[0]) * (box[3] - box[1])
    for region in find_regions(measurement.block_z, measurement.block_size):
        overlap_width = min(box[2], region.x + region.width) - max(box[0], region.x)
        overlap_height = min(box[3], region.y + region.height) - max(box[1], region.y)
        if overlap_width <= 0 or overlap_height <= 0:
            continue
        covers = overlap_width * overlap_height / patch_area >= HIT_COVERAGE
        if covers and region.width * region.height <= HIT_MAX_AREA_RATIO * patch_area:
            return True
    return False


def _measure_splices(
    items: Sequence[Item], limits: dict[str, float | None], loaded: Callable[[Item], Image.Image]
) -> dict:
    controls: dict[tuple[int, int], dict[str, Measurement]] = {}
    result: dict = {}
    for name, (paste, final_quality) in SPLICES.items():
        spliced_scores: dict[str, list[float]] = {test: [] for test in TEST_NAMES}
        control_scores: dict[str, list[float]] = {test: [] for test in TEST_NAMES}
        hits = dict.fromkeys(TEST_NAMES, 0)
        control_hits = dict.fromkeys(TEST_NAMES, 0)
        for position, item in enumerate(items):
            image = loaded(item)
            donor = loaded(items[(position + 1) % len(items)])
            image = image.copy()
            image.thumbnail((RESAVE_SIDE, RESAVE_SIDE), Image.Resampling.LANCZOS)
            box = _patch_box(image, position)
            spliced = _scores(_resaved(paste(image, donor, box), quality=final_quality, shrink=False))
            key = (position, final_quality)
            if key not in controls:
                controls[key] = _scores(_resaved(image, quality=final_quality, shrink=False))
            control = controls[key]
            for test in TEST_NAMES:
                if spliced[test].score is not None:
                    spliced_scores[test].append(spliced[test].score)
                if control[test].score is not None:
                    control_scores[test].append(control[test].score)
                hits[test] += _region_hit(spliced[test], box)
                control_hits[test] += _region_hit(control[test], box)
        result[name] = {
            test: {
                "against_same_image_without_the_patch": auc_with_interval(spliced_scores[test], control_scores[test]),
                "flagged": _flag_rate(spliced_scores[test], limits[test]),
                "flagged_without_the_patch": _flag_rate(control_scores[test], limits[test]),
                "region_found_on_patch": proportion(hits[test], len(items)) if test in _REGION_TESTS else None,
                "region_at_same_place_without_the_patch": (
                    proportion(control_hits[test], len(items)) if test in _REGION_TESTS else None
                ),
            }
            for test in TEST_NAMES
        }
    return result


def _flag_rate(scores: Sequence[float], limit: float | None) -> dict | None:
    if limit is None:
        return None
    return proportion(sum(score >= limit for score in scores), len(scores))


def _collect(rows: Sequence[dict], test: str, key: str, group: Callable[[dict], bool]) -> list[float]:
    return [row[key][test] for row in rows if group(row) and row[key].get(test) is not None]


def _whole_image(rows: Sequence[dict], limits: dict[str, float | None]) -> dict:
    conditions = {
        "files_as_they_are": ("original", lambda row: True),
        "jpeg_files_only": ("original", lambda row: row["format"] == "JPEG"),
        "all_re_saved_the_same_way": ("resaved", lambda row: True),
    }
    result: dict = {}
    for test in TEST_NAMES:
        entry = {}
        for condition, (key, keep) in conditions.items():
            if condition == "files_as_they_are" and test in JPEG_ONLY:
                # The check doesn't run these tests on other file types, so this comparison wouldn't apply.
                entry[condition] = None
                continue
            reals = _collect(rows, test, key, lambda row, keep=keep: keep(row) and row["label"] == REAL)
            groups = {}
            for group in (AI_GENERATED, EDITED):
                fakes = _collect(rows, test, key, lambda row, g=group, keep=keep: keep(row) and row["category"] == g)
                groups[group] = {**auc_with_interval(fakes, reals), "flagged": _flag_rate(fakes, limits[test])}
            entry[condition] = {"groups": groups, "real_flagged": _flag_rate(reals, limits[test])}
        result[test] = entry
    return result


def _beside_detector(rows: Sequence[dict], limits: dict[str, float | None], detector: dict[str, list]) -> dict | None:
    """Of the fakes the detector in use didn't flag, how many does each test flag, and at what false alarm rate?"""
    if not detector:
        return None
    usable = [row for row in rows if row["path"] in detector]
    missed = [row for row in usable if row["label"] == FAKE and detector[row["path"]][1] != "elevated"]
    reals = [row for row in usable if row["label"] == REAL]
    result = {
        "fakes_on_test_split": sum(row["label"] == FAKE for row in usable),
        "fakes_detector_did_not_flag": len(missed),
        "real_images_detector_flagged": sum(detector[row["path"]][1] == "elevated" for row in reals),
        "by_test": {},
    }
    for test in TEST_NAMES:
        limit = limits[test]
        applies = (lambda row: row["format"] == "JPEG") if test in JPEG_ONLY else (lambda row: True)
        result["by_test"][test] = {
            "fakes_detector_missed_that_this_flags": _flag_rate(_collect(missed, test, "original", applies), limit),
            "real_images_this_flags": _flag_rate(_collect(reals, test, "original", applies), limit),
        }
    return result


def _verdict(whole: dict, splices: dict) -> dict:
    """What each test showed, under the conditions where file type can't be what it is reading."""
    verdicts = {}
    for test in TEST_NAMES:
        fair_groups = []
        for group in (AI_GENERATED, EDITED):
            jpeg = whole[test]["jpeg_files_only"]["groups"][group]
            resaved = whole[test]["all_re_saved_the_same_way"]["groups"][group]
            if separates(jpeg) and separates(resaved):
                fair_groups.append(group)
        fair_splices = [
            name for name, entry in splices.items() if separates(entry[test]["against_same_image_without_the_patch"])
        ]
        verdicts[test] = {
            "separates_from_real_whichever_way_measured": fair_groups,
            "separates_spliced_from_unspliced": fair_splices,
            "adds_nothing": not fair_groups and not fair_splices,
        }
    return verdicts


def measure(
    real_dir: Path, fake_dir: Path, *, sources: Sequence[dict[str, str]], seed: int = 0, detector_cache: Path | None = None
) -> dict:
    config = MediaConfig()
    dataset = build_dataset(real_dir, fake_dir, config, seed=seed)
    rows: list[dict] = []
    seconds: list[float] = []
    largest = 0

    def loaded(item: Item) -> Image.Image:
        with Image.open(item.path) as image:
            return image.convert("RGB")

    for position, item in enumerate(dataset.items, start=1):
        with Image.open(item.path) as image:
            file_format = image.format
            rgb = image.convert("RGB")
        largest = max(largest, rgb.width * rgb.height)
        started = time.perf_counter()
        original = _scores(rgb)
        seconds.append(time.perf_counter() - started)
        row = {
            "path": str(item.path),
            "label": item.label,
            "category": item.category,
            "split": item.split,
            "format": file_format,
            "original": {name: value.score for name, value in original.items()},
        }
        if item.split == "test":
            row["resaved"] = {name: value.score for name, value in _scores(_resaved(rgb)).items()}
        rows.append(row)
        if position % 100 == 0:
            print(f"  measured {position} of {len(dataset.items)}", file=sys.stderr, flush=True)

    calibration = [row for row in rows if row["split"] == "calibration"]
    test_rows = [row for row in rows if row["split"] == "test"]
    limits: dict[str, float | None] = {}
    for test in TEST_NAMES:
        applies = (lambda row: row["format"] == "JPEG") if test in JPEG_ONLY else (lambda row: True)
        limits[test] = choose_limit(
            _collect(calibration, test, "original", lambda row, a=applies: a(row) and row["label"] == REAL)
        )

    whole = _whole_image(test_rows, limits)
    real_jpegs = [
        item
        for item in dataset.items
        if item.split == "test" and item.label == REAL and item.path.suffix.casefold() in {".jpg", ".jpeg"}
    ]
    print(f"  splicing {len(real_jpegs)} real JPEG images", file=sys.stderr, flush=True)
    splices = _measure_splices(real_jpegs, limits, loaded)

    detector = {}
    if detector_cache is not None:
        detector = ScoreCache(detector_cache, config.model_id, config.model_revision, config).entries

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "notice": NOTICE,
        "sources": list(sources),
        "settings": {
            "seed": seed,
            "target_real_flagged": TARGET_REAL_FLAGGED,
            "useful_auc": USEFUL_AUC,
            "re_saved_at": {"longest_side": RESAVE_SIDE, "jpeg_quality": RESAVE_QUALITY},
            "patch_area_share": 1 / PATCH_FRACTION**2,
            "max_pixels_examined": MAX_PIXELS,
        },
        "dataset": {
            "images": len(rows),
            "by_split": {"calibration": len(calibration), "test": len(test_rows)},
            "test_split_by_group_and_format": _format_mix(test_rows),
            "largest_megapixels": round(largest / 1e6, 1),
            "real_jpegs_spliced": len(real_jpegs),
        },
        "limits_chosen_on_calibration": limits,
        "verdicts": _verdict(whole, splices),
        "test_split": whole,
        "splices_on_test_split": splices,
        "beside_the_detector_in_use": _beside_detector(test_rows, limits, detector),
        "seconds_per_image_all_tests": {
            "median": round(float(np.median(seconds)), 3),
            "slowest": round(float(np.max(seconds)), 3),
        },
        "limitations": list(LIMITATIONS),
    }


def _format_mix(rows: Sequence[dict]) -> dict[str, dict[str, int]]:
    mix: dict[str, dict[str, int]] = {}
    for row in rows:
        group = mix.setdefault(row["category"], {})
        group[row["format"]] = group.get(row["format"], 0) + 1
    return {group: dict(sorted(formats.items())) for group, formats in sorted(mix.items())}


def main(argv: list[str] | None = None) -> int:
    import json

    parser = argparse.ArgumentParser(prog="python -m backend.media.eval.forensics", description=__doc__)
    parser.add_argument("--real", type=Path, required=True)
    parser.add_argument("--fake", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", action="append", required=True, help='as "name|licence|url"')
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--detector-cache", type=Path, help="saved scores from the benchmark, to compare with")
    args = parser.parse_args(argv)
    for folder in (args.real, args.fake):
        if not folder.is_dir():
            print(f"error: not a folder: {folder}", file=sys.stderr)
            return 2
    try:
        sources = [parse_source(text) for text in args.source]
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = measure(args.real, args.fake, sources=sources, seed=args.seed, detector_cache=args.detector_cache)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{result['dataset']['images']} images. Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
