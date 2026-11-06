"""Measure local feature matching on heavy crops, choosing its limit on the calibration split only.

    python -m backend.media.eval.crop_matching --real DIR --fake DIR --out data/eval/RESULT.json --source "name|licence|url"

Copies are made in memory and never written. Results hold only counts.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps

from backend.media.config import MediaConfig
from backend.media.eval.fingerprints import _caption_bar, _cropped, _recompressed
from backend.media.eval.metrics import proportion
from backend.media.eval.repost_variants import (
    _even,
    _panned_frames,
    _crop_each_side,
    clip_hashes,
    clips_match,
    combined_repost,
    square_centre_crop,
    watermark_corner,
    watermark_tiled,
    write_clip,
)
from backend.media.eval.runner import build_dataset, parse_source
from backend.media.keyframes import extract_keyframes
from backend.media.local_features import MAX_FEATURES, MAX_VIDEO_FRAMES, agreeing_features, best_agreement, compute_features, frame_features
from backend.media.metadata import read_image

SCHEMA = "crop-matching-eval-1"
# Stricter than the 0.1% used for single hashes, because a wrong link can join two unrelated groups.
TARGET_FALSE_MATCH_RATE = 0.0001
NOTICE = (
    "Measured on the listed images and these simulated changes only. A match shows that pictures share visible "
    "content, not who made them, where they first appeared or whether a claim about them is true."
)
LIMITATIONS = (
    "Changes were simulated in memory, not collected from real social media platforms.",
    "Some 'unrelated' pairs may really be related, such as photos from one series, which would raise the false match rate.",
    "Two different pictures sharing a logo, a screenshot frame or a large block of text can match.",
)


def _corner_crop(image: Image.Image) -> Image.Image:
    """Keep only the top-left 60% each way, so the kept part is far from the middle."""
    return image.crop((0, 0, image.width * 3 // 5, image.height * 3 // 5))


def _small(image: Image.Image) -> Image.Image:
    """A post's thumbnail: at most 400 pixels across and saved at low quality."""
    small = image.copy()
    small.thumbnail((400, 400), Image.Resampling.LANCZOS)
    return _recompressed(small)


CHANGES: dict[str, Callable[[Image.Image], Image.Image]] = {
    "thumbnail_400_pixels": _small,
    "cropped_10_percent_then_thumbnail_400_pixels": lambda image: _small(_crop_each_side(10)(image)),
    "cropped_20_percent_then_thumbnail_400_pixels": lambda image: _small(_crop_each_side(20)(image)),
    "recompressed_low_quality": _recompressed,
    "cropped_5_percent_each_side": _cropped,
    "cropped_10_percent_each_side": _crop_each_side(10),
    "cropped_20_percent_each_side": _crop_each_side(20),
    "cropped_30_percent_each_side": _crop_each_side(30),
    "cropped_to_square": square_centre_crop,
    "cropped_to_top_left_60_percent": _corner_crop,
    "caption_bar_added": _caption_bar,
    "watermark_tiled_faint": watermark_tiled,
    "watermark_small_corner_text": watermark_corner,
    "cropped_captioned_watermarked_recompressed": combined_repost,
    "cropped_20_percent_then_recompressed": lambda image: _recompressed(_crop_each_side(20)(image)),
    "mirrored": ImageOps.mirror,
}


VIDEO_CHANGES: dict[str, Callable[[Image.Image], Image.Image]] = {
    "cropped_10_percent_each_side": _crop_each_side(10),
    "cropped_20_percent_each_side": _crop_each_side(20),
    "cropped_to_square": square_centre_crop,
    "cropped_20_percent_captioned_watermarked": lambda frame: watermark_corner(_caption_bar(_crop_each_side(20)(frame))),
}
_VIDEO_WIDTH, _VIDEO_HEIGHT = 640, 360
_PICTURES_PER_CLIP = 3


def _clip_features(path: Path, config: MediaConfig) -> list[str]:
    _, frames, _ = extract_keyframes(path, config)
    return frame_features(frame.image for frame in frames)


def measure_video(items, config: MediaConfig, limit: int, clips: int) -> dict:
    """Heavily crop short clips, encode them, and compare the frames a case would keep."""
    ends = range(0, min(len(items), clips * _PICTURES_PER_CLIP), _PICTURES_PER_CLIP)
    groups = [group for group in (items[start : start + _PICTURES_PER_CLIP] for start in ends) if len(group) == _PICTURES_PER_CLIP]
    originals: list[list[str]] = []
    by_features = dict.fromkeys(VIDEO_CHANGES, 0)
    by_hashes = dict.fromkeys(VIDEO_CHANGES, 0)
    with tempfile.TemporaryDirectory(prefix="trustfeed-crop-eval-") as raw:
        path = Path(raw) / "clip.mp4"
        for number, group in enumerate(groups, start=1):
            pictures = [read_image(item.path, config)[0].convert("RGB").resize((_VIDEO_WIDTH, _VIDEO_HEIGHT)) for item in group]

            def build(change: Callable[[Image.Image], Image.Image], bit_rate: int) -> None:
                write_clip(path, [_even(change(frame)) for picture in pictures for frame in _panned_frames(picture)], bit_rate=bit_rate)

            build(lambda frame: frame, 1_500_000)
            original = _clip_features(path, config)
            hashes = clip_hashes(path, config)
            originals.append(original)
            for name, change in VIDEO_CHANGES.items():
                build(change, 300_000)
                by_features[name] += best_agreement(original, _clip_features(path, config)) >= limit
                by_hashes[name] += clips_match(hashes, clip_hashes(path, config))
            if number % 10 == 0:
                print(f"  built {number} of {len(groups)} clips", file=sys.stderr, flush=True)
    pairs = false_matches = 0
    for left in range(len(originals)):
        for right in range(left + 1, len(originals)):
            pairs += 1
            false_matches += best_agreement(originals[left], originals[right]) >= limit
    return {
        "clips": len(originals),
        "frames_kept_per_clip": MAX_VIDEO_FRAMES,
        "copies_matched_by_local_features": {name: proportion(count, len(originals)) for name, count in by_features.items()},
        "copies_matched_by_whole_picture_hashes": {name: proportion(count, len(originals)) for name, count in by_hashes.items()},
        "unrelated_clip_pairs_wrongly_matched": proportion(false_matches, pairs),
    }


def _unrelated(features: Sequence[str]) -> Counter[int]:
    counts: Counter[int] = Counter()
    for left in range(len(features)):
        for right in range(left + 1, len(features)):
            counts[agreeing_features(features[left], features[right])] += 1
    return counts


def choose_limit(counts: Counter[int], target: float = TARGET_FALSE_MATCH_RATE) -> int:
    """The lowest number of agreeing patches at which unrelated pairs match no more often than the target."""
    total = sum(counts.values())
    highest = max(counts, default=0)
    for limit in range(1, highest + 2):
        if sum(count for value, count in counts.items() if value >= limit) / total <= target:
            return limit
    return highest + 1


def measure(real_dir: Path, fake_dir: Path, *, sources: Sequence[dict[str, str]], clips: int = 40, seed: int = 0) -> dict:
    config = MediaConfig()
    dataset = build_dataset(real_dir, fake_dir, config, seed=seed)
    features: dict[str, list[str]] = {"calibration": [], "test": []}
    missing = Counter()
    copies: dict[str, list[int]] = {name: [] for name in CHANGES}
    sizes = []
    started = time.perf_counter()
    for position, item in enumerate(dataset.items, start=1):
        image, _, _ = read_image(item.path, config)
        image = image.convert("RGB")
        original = compute_features(image)
        if original is None:
            missing[item.split] += 1
            if item.split == "test":
                for rows in copies.values():
                    rows.append(0)
            continue
        features[item.split].append(original)
        sizes.append(len(original))
        if item.split == "test":
            for name, change in CHANGES.items():
                changed = compute_features(change(image))
                copies[name].append(agreeing_features(original, changed) if changed else 0)
        if position % 100 == 0:
            print(f"  {position} of {len(dataset.items)} ({time.perf_counter() - started:.0f}s)", file=sys.stderr, flush=True)
    print("  comparing unrelated pairs", file=sys.stderr, flush=True)
    started = time.perf_counter()
    calibration = _unrelated(features["calibration"])
    limit = choose_limit(calibration)
    test = _unrelated(features["test"])
    seconds = time.perf_counter() - started
    pairs = sum(calibration.values()) + sum(test.values())
    false_on_test = sum(count for value, count in test.items() if value >= limit)
    print("  measuring video", file=sys.stderr, flush=True)
    video = measure_video([item for item in dataset.items if item.split == "test"], config, limit, clips)
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "notice": NOTICE,
        "sources": list(sources),
        "settings": {"seed": seed, "target_false_match_rate": TARGET_FALSE_MATCH_RATE, "max_features": MAX_FEATURES},
        "limit_chosen_on_calibration": limit,
        "pictures_without_enough_detail": dict(missing),
        "saved_size_bytes_median": sorted(sizes)[len(sizes) // 2] if sizes else None,
        "milliseconds_per_comparison": round(1000 * seconds / pairs, 2) if pairs else None,
        "test_split": {
            "copies_matched": {name: proportion(sum(value >= limit for value in rows), len(rows)) for name, rows in copies.items()},
            "unrelated_pairs_wrongly_matched": proportion(false_on_test, sum(test.values())),
        },
        "video_test_split": video,
        "limitations": list(LIMITATIONS),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.media.eval.crop_matching", description=__doc__)
    parser.add_argument("--real", type=Path, required=True)
    parser.add_argument("--fake", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", action="append", required=True, help='as "name|licence|url"')
    args = parser.parse_args(argv)
    result = measure(args.real, args.fake, sources=[parse_source(text) for text in args.source])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("limit_chosen_on_calibration", "saved_size_bytes_median", "milliseconds_per_comparison", "test_split", "video_test_split")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
