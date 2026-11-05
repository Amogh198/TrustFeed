"""Measure how far fingerprints move on altered copies, and how often unrelated images match.

    python -m backend.media.eval.fingerprints --real DIR --fake DIR --out data/eval/RESULT.json \
        --source "name|licence|url"

Copies are made in memory and never written. The results hold only counts, never images or file names.
Distance limits are chosen on the calibration split and measured on the test split.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageOps

from backend.media.config import MediaConfig
from backend.media.eval.metrics import proportion
from backend.media.eval.runner import build_dataset, parse_source
from backend.media.fingerprint import HASH_KINDS, compute_fingerprints, fingerprint_distances
from backend.media.metadata import read_image

SCHEMA = "fingerprint-eval-1"
# Unrelated images may match at most this often when a limit is chosen.
TARGET_FALSE_MATCH_RATE = 0.001
STRUCTURAL_KINDS = ("phash", "dhash", "whash")
EXISTING_PHASH_LIMIT = 5
_MAX_SIDE = 800
_QUALITY = 40
NOTICE = (
    "Measured on the listed images and these simulated changes only. A match shows visual similarity, not who made "
    "an image, where it first appeared or whether a claim about it is true."
)
LIMITATIONS = (
    "Changes were simulated in memory, not collected from real social media platforms.",
    "Some 'unrelated' pairs may really be related, such as photos from one series, which would raise the false "
    "match rate.",
    "Labels are as stated by whoever ran this benchmark. The tool does not check them.",
)


def _recompressed(image: Image.Image) -> Image.Image:
    import io

    copy = image.copy()
    copy.thumbnail((_MAX_SIDE, _MAX_SIDE), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    copy.save(buffer, format="JPEG", quality=_QUALITY)
    buffer.seek(0)
    with Image.open(buffer) as reopened:
        return reopened.convert("RGB")


def _resized(image: Image.Image) -> Image.Image:
    return image.resize((max(1, image.width // 2), max(1, image.height // 2)), Image.Resampling.BILINEAR)


def _cropped(image: Image.Image) -> Image.Image:
    x, y = image.width // 20, image.height // 20
    return image.crop((x, y, image.width - x, image.height - y))


def _caption_bar(image: Image.Image) -> Image.Image:
    copy = image.copy()
    height = max(1, copy.height // 8)
    draw = ImageDraw.Draw(copy)
    draw.rectangle((0, copy.height - height, copy.width, copy.height), fill=(0, 0, 0))
    draw.rectangle((copy.width // 10, copy.height - height * 2 // 3, copy.width * 9 // 10, copy.height - height // 3), fill=(255, 255, 255))
    return copy


def _brightened(image: Image.Image) -> Image.Image:
    return ImageEnhance.Brightness(image).enhance(1.2)


ALTERATIONS: dict[str, Callable[[Image.Image], Image.Image]] = {
    "recompressed_low_quality": _recompressed,
    "resized_to_half": _resized,
    "cropped_5_percent_each_side": _cropped,
    "caption_bar_added": _caption_bar,
    "brightened_20_percent": _brightened,
    "mirrored": ImageOps.mirror,
}


def choose_limit(unrelated: Counter[int], pair_count: int, target: float = TARGET_FALSE_MATCH_RATE) -> int | None:
    """The largest distance at which unrelated pairs match no more often than the target."""
    if not pair_count:
        return None
    best = None
    seen = 0
    for distance in range(max(unrelated, default=0) + 1):
        seen += unrelated.get(distance, 0)
        if seen / pair_count > target:
            break
        best = distance
    return best


def rule_matches(distances: dict[str, int], limits: dict[str, int | None], kinds: Sequence[str], needed: int) -> bool:
    agreeing = sum(
        1 for kind in kinds if limits.get(kind) is not None and kind in distances and distances[kind] <= limits[kind]
    )
    return agreeing >= needed


def _percentiles(counter: Counter[int]) -> dict[str, int] | None:
    values = sorted(counter.elements())
    if not values:
        return None
    return {f"p{p}": values[min(len(values) - 1, len(values) * p // 100)] for p in (50, 90, 99)}


def _pairs(fingerprints: Sequence[dict[str, str]]):
    for left in range(len(fingerprints)):
        for right in range(left + 1, len(fingerprints)):
            yield fingerprint_distances(fingerprints[left], fingerprints[right])


def _unrelated_counts(fingerprints: Sequence[dict[str, str]]) -> tuple[dict[str, Counter[int]], int]:
    counts: dict[str, Counter[int]] = {kind: Counter() for kind in HASH_KINDS}
    total = 0
    for distances in _pairs(fingerprints):
        total += 1
        for kind, distance in distances.items():
            counts[kind][distance] += 1
    return counts, total


def _measure_rules(
    fingerprints: Sequence[dict[str, str]],
    copies: dict[str, list[dict[str, int]]],
    rules: dict[str, tuple[dict[str, int | None], Sequence[str], int]],
) -> dict[str, dict]:
    pair_distances = list(_pairs(fingerprints))
    result = {}
    for name, (limits, kinds, needed) in rules.items():
        false_matches = sum(rule_matches(distances, limits, kinds, needed) for distances in pair_distances)
        result[name] = {
            "limits": {kind: limits.get(kind) for kind in kinds},
            "needed": needed,
            "false_match_rate": proportion(false_matches, len(pair_distances)),
            "copies_matched": {
                alteration: proportion(sum(rule_matches(d, limits, kinds, needed) for d in rows), len(rows))
                for alteration, rows in copies.items()
            },
        }
    return result


def measure(real_dir: Path, fake_dir: Path, *, sources: Sequence[dict[str, str]], seed: int = 0) -> dict:
    config = MediaConfig()
    dataset = build_dataset(real_dir, fake_dir, config, seed=seed)
    split_fingerprints: dict[str, list[dict[str, str]]] = {"calibration": [], "test": []}
    split_copies: dict[str, dict[str, list[dict[str, int]]]] = {
        split: {name: [] for name in ALTERATIONS} for split in split_fingerprints
    }
    for position, item in enumerate(dataset.items, start=1):
        image, _, _ = read_image(item.path, config)
        image = image.convert("RGB")
        original = compute_fingerprints(image)
        split_fingerprints[item.split].append(original)
        for name, alter in ALTERATIONS.items():
            split_copies[item.split][name].append(fingerprint_distances(original, compute_fingerprints(alter(image))))
        if position % 100 == 0:
            print(f"  fingerprinted {position} of {len(dataset.items)}", file=sys.stderr, flush=True)

    calibration_counts, calibration_pairs = _unrelated_counts(split_fingerprints["calibration"])
    limits = {kind: choose_limit(calibration_counts[kind], calibration_pairs) for kind in HASH_KINDS}
    test_counts, test_pairs = _unrelated_counts(split_fingerprints["test"])
    rules: dict[str, tuple[dict[str, int | None], Sequence[str], int]] = {
        f"{kind}_alone": (limits, (kind,), 1) for kind in HASH_KINDS
    }
    rules["existing_phash_limit"] = ({"phash": EXISTING_PHASH_LIMIT}, ("phash",), 1)
    rules["any_two_structural"] = (limits, STRUCTURAL_KINDS, 2)
    rules["any_one_structural"] = (limits, STRUCTURAL_KINDS, 1)

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "notice": NOTICE,
        "sources": list(sources),
        "settings": {"seed": seed, "target_false_match_rate": TARGET_FALSE_MATCH_RATE},
        "dataset": {
            "images": len(dataset.items),
            "by_split": {split: len(values) for split, values in split_fingerprints.items()},
            "unrelated_pairs": {"calibration": calibration_pairs, "test": test_pairs},
        },
        "limits_chosen_on_calibration": limits,
        "test_split": _measure_rules(split_fingerprints["test"], split_copies["test"], rules),
        "distances_on_test_split": {
            kind: {
                "unrelated_pairs": _percentiles(test_counts[kind]),
                "copies": {
                    name: _percentiles(Counter(row[kind] for row in rows if kind in row))
                    for name, rows in split_copies["test"].items()
                },
            }
            for kind in HASH_KINDS
        },
        "limitations": list(LIMITATIONS),
    }


def main(argv: list[str] | None = None) -> int:
    import json

    parser = argparse.ArgumentParser(prog="python -m backend.media.eval.fingerprints", description=__doc__)
    parser.add_argument("--real", type=Path, required=True)
    parser.add_argument("--fake", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", action="append", required=True, help='as "name|licence|url"')
    parser.add_argument("--seed", type=int, default=0)
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
    result = measure(args.real, args.fake, sources=sources, seed=args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{result['dataset']['images']} images. Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
