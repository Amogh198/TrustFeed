"""Measure the fingerprint rule on repost changes the first benchmark left out: watermarks, larger crops and video.

    python -m backend.media.eval.repost_variants --real DIR --fake DIR --out data/eval/RESULT.json \
        --source "name|licence|url"

Uses the test split of backend.media.eval.fingerprints, with the limits already in use, so nothing here is tuned
on these results. Copies are made in a temporary folder and deleted. Results hold only counts.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from backend.media.config import MediaConfig
from backend.media.eval.fingerprints import _caption_bar, _cropped, _recompressed
from backend.media.eval.metrics import proportion
from backend.media.eval.runner import build_dataset, parse_source
from backend.media.fingerprint import (
    QueryFrame,
    compute_fingerprints,
    find_matches,
    same_picture,
)
from backend.media.keyframes import extract_keyframes
from backend.media.metadata import read_image

SCHEMA = "repost-variants-eval-1"
_VIDEO_SIZE = 640
_SECONDS_PER_PICTURE = 2
_RATE = 10
PICTURES_PER_CLIP = 3
NOTICE = (
    "Measured on the listed images and these simulated changes only. A match shows visual similarity, not who made "
    "a file, where it first appeared or whether a claim about it is true."
)
LIMITATIONS = (
    "Changes were simulated, not collected from real social media platforms.",
    "Watermarks here are plain text and a small logo shape. Real ones vary in size, placement and strength.",
    "Clips were built from still pictures with a slow pan, not filmed video, so real video may behave differently.",
    "Some 'unrelated' pairs may really be related, such as photos from one series.",
)


def _font(size: int):
    try:
        return ImageFont.load_default(size=max(10, size))
    except TypeError:
        return ImageFont.load_default()


def _text_layer(image: Image.Image) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    return layer, ImageDraw.Draw(layer)


def _flatten(image: Image.Image, layer: Image.Image) -> Image.Image:
    return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")


def watermark_corner(image: Image.Image) -> Image.Image:
    """A small, solid mark in one corner, as many accounts add."""
    layer, draw = _text_layer(image)
    size = image.height // 18
    draw.text((image.width // 40, image.height - size * 2), "@some_account", font=_font(size), fill=(255, 255, 255, 230))
    return _flatten(image, layer)


def watermark_centre(image: Image.Image) -> Image.Image:
    """One large see-through mark across the middle."""
    layer, draw = _text_layer(image)
    size = image.height // 7
    draw.text((image.width // 2, image.height // 2), "SAMPLE WATERMARK", font=_font(size), fill=(255, 255, 255, 110), anchor="mm")
    return _flatten(image, layer)


def watermark_tiled(image: Image.Image) -> Image.Image:
    """A faint mark repeated across the whole picture, the hardest common kind."""
    layer, draw = _text_layer(image)
    size = max(12, image.height // 16)
    for row in range(0, image.height, size * 4):
        for column in range(0, image.width, size * 8):
            draw.text((column + (row // 2) % (size * 4), row), "repost.example", font=_font(size), fill=(255, 255, 255, 80))
    return _flatten(image, layer)


def logo_corner(image: Image.Image) -> Image.Image:
    layer, draw = _text_layer(image)
    side = min(image.size) // 7
    draw.ellipse((image.width - side * 5 // 4, side // 4, image.width - side // 4, side * 5 // 4), fill=(220, 40, 40, 235))
    return _flatten(image, layer)


def _crop_each_side(share: int) -> Callable[[Image.Image], Image.Image]:
    def crop(image: Image.Image) -> Image.Image:
        x, y = image.width * share // 100, image.height * share // 100
        return image.crop((x, y, image.width - x, image.height - y))

    return crop


def square_centre_crop(image: Image.Image) -> Image.Image:
    """The crop a square feed makes, which removes much more from one direction."""
    side = min(image.size)
    x, y = (image.width - side) // 2, (image.height - side) // 2
    return image.crop((x, y, x + side, y + side))


def combined_repost(image: Image.Image) -> Image.Image:
    """A realistic repost: cropped, captioned, marked, shrunk and saved at low quality."""
    return _recompressed(watermark_corner(_caption_bar(_cropped(image))))


IMAGE_CHANGES: dict[str, Callable[[Image.Image], Image.Image]] = {
    "watermark_small_corner_text": watermark_corner,
    "watermark_logo_corner": logo_corner,
    "watermark_large_centre_see_through": watermark_centre,
    "watermark_tiled_faint": watermark_tiled,
    "cropped_10_percent_each_side": _crop_each_side(10),
    "cropped_20_percent_each_side": _crop_each_side(20),
    "cropped_to_square": square_centre_crop,
    "cropped_captioned_watermarked_recompressed": combined_repost,
}

VIDEO_CHANGES: dict[str, Callable[[Image.Image], Image.Image]] = {
    "same_frames_reencoded_low_quality": lambda frame: frame,
    "resized_to_half": lambda frame: frame.resize((frame.width // 2 // 2 * 2, frame.height // 2 // 2 * 2), Image.Resampling.BILINEAR),
    "cropped_5_percent_each_side": _cropped,
    "caption_bar_added": _caption_bar,
    "watermark_small_corner_text": watermark_corner,
    "cropped_captioned_watermarked": lambda frame: watermark_corner(_caption_bar(_cropped(frame))),
}


def _even(image: Image.Image) -> Image.Image:
    return image.crop((0, 0, image.width // 2 * 2, image.height // 2 * 2))


def _panned_frames(picture: Image.Image) -> list[Image.Image]:
    """Show a still picture with a slow sideways pan, so frames in one shot aren't all identical."""
    picture = picture.copy()
    picture.thumbnail((_VIDEO_SIZE, _VIDEO_SIZE), Image.Resampling.LANCZOS)
    count = _SECONDS_PER_PICTURE * _RATE
    room = max(1, picture.width // 25)
    frames = []
    for index in range(count):
        offset = room * index // count
        frames.append(_even(picture.crop((offset, 0, picture.width - room + offset, picture.height))))
    return frames


def write_clip(path: Path, frames: Sequence[Image.Image], *, bit_rate: int) -> None:
    import av

    size = frames[0].size
    with av.open(str(path), "w") as container:
        stream = container.add_stream("mpeg4", rate=_RATE)
        stream.width, stream.height, stream.pix_fmt, stream.bit_rate = size[0], size[1], "yuv420p", bit_rate
        for frame in frames:
            still = frame if frame.size == size else frame.resize(size)
            for packet in stream.encode(av.VideoFrame.from_image(still.convert("RGB"))):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def clip_hashes(path: Path, config: MediaConfig) -> list[dict[str, str]]:
    _, frames, _ = extract_keyframes(path, config)
    return [compute_fingerprints(frame.image) for frame in frames]


def clips_match(left: Sequence[dict[str, str]], right: Sequence[dict[str, str]]) -> bool:
    """The rule the app uses: any frame of one looking like any frame of the other."""
    from backend.media.fingerprint import CaseFingerprint

    query = [QueryFrame(None, hashes) for hashes in left]
    return bool(find_matches(None, query, [], [CaseFingerprint(case_id="other", seen_at="", frames=list(right))]))


def _measure_images(items, config: MediaConfig) -> dict:
    counts = dict.fromkeys(IMAGE_CHANGES, 0)
    total = 0
    for item in items:
        image, _, _ = read_image(item.path, config)
        image = image.convert("RGB")
        original = compute_fingerprints(image)
        total += 1
        for name, change in IMAGE_CHANGES.items():
            counts[name] += same_picture(original, compute_fingerprints(change(image)))
    return {name: proportion(count, total) for name, count in counts.items()}


def _encoded_changed(picture: Image.Image, change, folder: Path, name: str, bit_rate: int) -> Path:
    path = folder / f"{name}.mp4"
    frames = [_even(change(frame)) for frame in _panned_frames(picture)]
    write_clip(path, frames, bit_rate=bit_rate)
    return path


def _measure_video(items, config: MediaConfig, clips: int) -> dict:
    groups = [items[index : index + PICTURES_PER_CLIP] for index in range(0, min(len(items), clips * PICTURES_PER_CLIP), PICTURES_PER_CLIP)]
    groups = [group for group in groups if len(group) == PICTURES_PER_CLIP]
    originals: list[list[dict[str, str]]] = []
    counts = {**dict.fromkeys(VIDEO_CHANGES, 0), "second_half_only": 0}
    image_to_clip = 0
    with tempfile.TemporaryDirectory(prefix="trustfeed-repost-eval-") as raw:
        folder = Path(raw)
        for number, group in enumerate(groups, start=1):
            pictures = []
            for item in group:
                picture, _, _ = read_image(item.path, config)
                # One size per clip, as a real video has.
                pictures.append(picture.convert("RGB").resize((_VIDEO_SIZE, _VIDEO_SIZE * 9 // 16), Image.Resampling.LANCZOS))

            def build(change, bit_rate: int, use=pictures) -> Path:
                frames = [_even(change(frame)) for picture in use for frame in _panned_frames(picture)]
                path = folder / "clip.mp4"
                write_clip(path, frames, bit_rate=bit_rate)
                return path

            original = clip_hashes(build(lambda frame: frame, 1_500_000), config)
            originals.append(original)
            for name, change in VIDEO_CHANGES.items():
                counts[name] += clips_match(original, clip_hashes(build(change, 300_000), config))
            counts["second_half_only"] += clips_match(original, clip_hashes(build(lambda frame: frame, 300_000, pictures[1:]), config))
            # A screenshot of one moment, posted as an image.
            buffer = io.BytesIO()
            pictures[1].save(buffer, format="JPEG", quality=50)
            buffer.seek(0)
            with Image.open(buffer) as still:
                image_to_clip += clips_match([compute_fingerprints(still.convert("RGB"))], original)
            if number % 10 == 0:
                print(f"  built {number} of {len(groups)} clips", file=sys.stderr, flush=True)
    pairs = 0
    false_matches = 0
    for left in range(len(originals)):
        for right in range(left + 1, len(originals)):
            pairs += 1
            false_matches += clips_match(originals[left], originals[right])
    total = len(originals)
    return {
        "clips": total,
        "seconds_each": PICTURES_PER_CLIP * _SECONDS_PER_PICTURE,
        "copies_matched": {
            **{name: proportion(count, total) for name, count in counts.items()},
            "still_screenshot_to_clip": proportion(image_to_clip, total),
        },
        "unrelated_clip_pairs_wrongly_matched": proportion(false_matches, pairs),
    }


def measure(real_dir: Path, fake_dir: Path, *, sources: Sequence[dict[str, str]], clips: int, seed: int = 0) -> dict:
    config = MediaConfig()
    dataset = build_dataset(real_dir, fake_dir, config, seed=seed)
    test_items = [item for item in dataset.items if item.split == "test"]
    print(f"  {len(test_items)} test images", file=sys.stderr, flush=True)
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "notice": NOTICE,
        "sources": list(sources),
        "settings": {"seed": seed, "rule": "two of pHash, dHash and wHash within the limits in backend/media/fingerprint.py"},
        "image_copies_matched": _measure_images(test_items, config),
        "video": _measure_video(test_items, config, clips),
        "limitations": list(LIMITATIONS),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.media.eval.repost_variants", description=__doc__)
    parser.add_argument("--real", type=Path, required=True)
    parser.add_argument("--fake", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", action="append", required=True, help='as "name|licence|url"')
    parser.add_argument("--clips", type=int, default=40)
    args = parser.parse_args(argv)
    result = measure(args.real, args.fake, sources=[parse_source(text) for text in args.source], clips=args.clips)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"images": result["image_copies_matched"], "video": result["video"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
