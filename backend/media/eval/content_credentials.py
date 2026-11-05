"""Measure the Content Credentials check: how many images carry credentials, and known answers on signed copies.

    python -m backend.media.eval.content_credentials --real DIR --fake DIR --out data/eval/RESULT.json \
        --source "name|licence|url"

Signed copies use a throwaway certificate, stay in a temporary folder and are deleted afterwards.
The results hold only counts and times, never images, file names or signer names.
"""

from __future__ import annotations

import argparse
import io
import json
import random
import statistics
import struct
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from backend.media.config import MediaConfig
from backend.media.content_credentials import (
    INVALID,
    SIGNED,
    _read_report,
    declares_ai,
    offline_settings,
    read_credentials,
)
from backend.media.eval.runner import build_dataset, parse_source
from backend.media.eval.throwaway_signer import ThrowawaySigner, make_signer, sign_bytes
from backend.media.metadata import sniff_media_type
from backend.media.models import ContentCredentialsCheck

SCHEMA = "content-credentials-eval-2"
_MIMES = {"jpeg": "image/jpeg", "png": "image/png"}
LIMITATIONS = (
    "The known-answer and byte-changing tests used copies signed here with a throwaway certificate. Only the scan read "
    "credentials written by real tools, and those files were not known to be right or wrong in advance.",
    "No trust list was used, so whether any signer can be trusted was not measured. Signers' names are claims.",
    "Commons may keep or remove credentials on upload, so the scan says little about how common they are elsewhere.",
    "Labels are as stated by whoever ran this measurement. The tool does not check them.",
)


def _state_of(check: ContentCredentialsCheck) -> str:
    return check.state or check.status.value


def _outcome(path: Path, config: MediaConfig) -> str:
    return _state_of(read_credentials(path, config))


def _state_with_library_default_usages(path: Path) -> str:
    """Read again without the list of accepted certificate usages, to measure what that list changes."""
    import c2pa

    settings = offline_settings()
    del settings["trust"]
    try:
        return str(_read_report(path, c2pa, settings).get("validation_state"))
    except Exception as exc:
        return type(exc).__name__


def _scan(items: Sequence, config: MediaConfig) -> dict:
    found: dict[str, Counter] = {}
    reasons: Counter = Counter()
    codes: Counter = Counter()
    declared_ai: Counter = Counter()
    with_defaults: Counter = Counter()
    seconds = []
    for item in items:
        started = time.perf_counter()
        check = read_credentials(item.path, config)
        seconds.append(time.perf_counter() - started)
        state = _state_of(check)
        found.setdefault(f"{item.label}/{item.category}", Counter())[state] += 1
        if check.invalid_reason:
            reasons[check.invalid_reason] += 1
        codes.update(check.failure_codes)
        if declares_ai(check):
            declared_ai[state if not check.invalid_reason else f"{state}/{check.invalid_reason}"] += 1
        if state in (SIGNED, INVALID):
            with_defaults[f"{state} here, {_state_with_library_default_usages(item.path)} with the library's default usages"] += 1
    return {
        "images": len(items),
        "by_kind": {kind: dict(counts) for kind, counts in sorted(found.items())},
        "invalid_reasons": dict(reasons),
        "failure_codes": dict(codes),
        "declares_ai_content": dict(declared_ai),
        "effect_of_accepted_usages": dict(with_defaults),
        "read_time_ms": {
            "median": round(statistics.median(seconds) * 1000, 1) if seconds else None,
            "slowest": round(max(seconds) * 1000, 1) if seconds else None,
        },
    }


def _resaved(payload: bytes) -> bytes:
    buffer = io.BytesIO()
    with Image.open(io.BytesIO(payload)) as image:
        image.convert("RGB").save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def _first_difference(first: Any, second: Any) -> int:
    size = min(len(first), len(second))
    differing = (first[:size] != second[:size]).nonzero()[0]
    return int(differing[0]) if differing.size else size


def _original_bytes(original: bytes, signed: bytes) -> tuple[int, int]:
    """Find offsets in a signed copy that still hold the original file, away from its headers, by comparing the two."""
    import numpy as np

    plain = np.frombuffer(original, np.uint8)
    copy = np.frombuffer(signed, np.uint8)
    head = _first_difference(plain, copy)
    tail = _first_difference(plain[::-1], copy[::-1])
    start, end = (len(signed) - tail, len(signed)) if tail >= head else (0, head)
    return start + (end - start) // 2, end - 16


def _known_answers(items: Sequence, signer: ThrowawaySigner, config: MediaConfig, folder: Path, rng: random.Random) -> dict:
    """Sign real images, then change or re-save the copies. The right answer for each is known."""
    results: dict[str, Counter] = {"signed_copy": Counter(), "byte_changed_in_image_data": Counter(), "re_saved": Counter()}
    path = folder / "copy"
    used = 0
    for item in items:
        payload = item.path.read_bytes()
        sniffed = sniff_media_type(payload[:16])
        mime = _MIMES.get(sniffed[1]) if sniffed else None
        if mime is None:
            continue
        signed = sign_bytes(payload, mime, signer)
        path.write_bytes(signed)
        results["signed_copy"][_outcome(path, config)] += 1
        changed = bytearray(signed)
        changed[rng.randrange(*_original_bytes(payload, signed))] ^= 0x01
        path.write_bytes(changed)
        results["byte_changed_in_image_data"][_outcome(path, config)] += 1
        path.write_bytes(_resaved(signed))
        results["re_saved"][_outcome(path, config)] += 1
        used += 1
    path.unlink(missing_ok=True)
    return {"images": used, "expected": {"signed_copy": "signed", "byte_changed_in_image_data": "invalid", "re_saved": "unsigned"}} | {
        name: dict(counts) for name, counts in results.items()
    }


def _small_video(folder: Path) -> bytes:
    import cv2
    import numpy as np

    path = folder / "small.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 120))
    generator = np.random.default_rng(0)
    for _ in range(30):
        writer.write(generator.integers(0, 256, (120, 160, 3), dtype=np.uint8))
    writer.release()
    payload = path.read_bytes()
    path.unlink()
    return payload


def _box_range(payload: bytes, kind: bytes) -> tuple[int, int]:
    position = 0
    while position + 8 <= len(payload):
        size, name = struct.unpack(">I4s", payload[position : position + 8])
        if name == kind:
            return position + 8, position + size
        position += size
    raise ValueError(f"No {kind!r} box was found.")


def _reported(check: ContentCredentialsCheck) -> tuple:
    return (
        check.signer_organisation,
        check.claim_generator,
        check.signed_at,
        tuple(check.declared_sources),
        tuple(check.declared_in_history),
        check.signer_trust,
    )


def _flip_each(signed: bytes, offsets: Sequence[int], config: MediaConfig, path: Path) -> dict:
    """Some bytes in a file are not covered by its signature. Can changing one alter what a signed result reports?"""
    path.write_bytes(signed)
    wanted = _reported(read_credentials(path, config))
    outcomes: Counter = Counter()
    report_changed = 0
    for offset in offsets:
        changed = bytearray(signed)
        changed[offset] ^= 0x01
        path.write_bytes(changed)
        check = read_credentials(path, config)
        outcomes[_state_of(check)] += 1
        if check.state == SIGNED and _reported(check) != wanted:
            report_changed += 1
    return {"bytes_changed": len(offsets), "outcomes": dict(outcomes), "still_signed_but_report_differs": report_changed}


def _sweep(signer: ThrowawaySigner, plain_video: bytes, config: MediaConfig, folder: Path, step: int, video_step: int) -> dict:
    path = folder / "sweep"
    video = sign_bytes(plain_video, "video/mp4", signer, source_type="trainedAlgorithmicMedia")
    start, end = _box_range(video, b"uuid")
    buffer = io.BytesIO()
    Image.effect_noise((64, 64), 40).convert("RGB").save(buffer, format="JPEG")
    jpeg = sign_bytes(buffer.getvalue(), "image/jpeg", signer, source_type="trainedAlgorithmicMedia")
    results = {
        f"signed_video_credentials_block_every_{video_step}_bytes": _flip_each(video, range(start - 8, end, video_step), config, path),
        "signed_video_file_type_header_every_byte": _flip_each(video, range(*_box_range(video, b"ftyp")), config, path),
        f"signed_jpeg_every_{step}_bytes": _flip_each(jpeg, range(0, len(jpeg), step), config, path),
    }
    path.unlink(missing_ok=True)
    return results


def _video(
    signer: ThrowawaySigner, plain: bytes, config: MediaConfig, folder: Path, rng: random.Random, flips: int, size_mb: int
) -> dict:
    """Changed bytes in the video data, and the read time for a file at the upload limit, which the time limit must allow."""
    signed = sign_bytes(plain, "video/mp4", signer)
    path = folder / "video.mp4"
    start, end = _box_range(signed, b"mdat")
    changed_data: Counter = Counter()
    for _ in range(flips):
        changed = bytearray(signed)
        changed[rng.randrange(start, end)] ^= 0x01
        path.write_bytes(changed)
        changed_data[_outcome(path, config)] += 1
    # A second "mdat" box makes the file large. Unlike a "free" box, the signature's hash has to read all of it.
    size = size_mb * 1024 * 1024
    large = bytearray(sign_bytes(plain + struct.pack(">I4s", size + 8, b"mdat") + bytes(size), "video/mp4", signer))
    path.write_bytes(large)
    started = time.perf_counter()
    outcome = _outcome(path, config)
    seconds = time.perf_counter() - started
    large[-size // 2] ^= 0x01
    path.write_bytes(large)
    changed_outcome = _outcome(path, config)
    size_on_disk = path.stat().st_size
    path.unlink()
    return {
        "byte_changed_in_video_data": {"tried": flips, "expected": "invalid", **dict(changed_data)},
        "file_at_upload_limit": {
            "size_mb": round(size_on_disk / (1024 * 1024), 1),
            "outcome": outcome,
            "read_seconds": round(seconds, 2),
            "outcome_after_changing_one_byte_in_the_middle": changed_outcome,
        },
    }


def measure(
    real_dir: Path,
    fake_dir: Path,
    *,
    sources: Sequence[dict[str, str]],
    seed: int = 0,
    sample: int = 100,
    flips: int = 200,
    large_video_mb: int = 200,
    sweep_step: int = 23,
    video_sweep_step: int = 1,
) -> dict:
    config = MediaConfig()
    dataset = build_dataset(real_dir, fake_dir, config, seed=seed)
    rng = random.Random(seed)
    signer = make_signer()
    chosen = rng.sample(list(dataset.items), min(sample, len(dataset.items)))
    with tempfile.TemporaryDirectory() as temporary:
        folder = Path(temporary)
        known = _known_answers(chosen, signer, config, folder, rng)
        plain_video = _small_video(folder)
        video = _video(signer, plain_video, config, folder, rng, flips, large_video_mb)
        sweep = _sweep(signer, plain_video, config, folder, sweep_step, video_sweep_step)
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "notice": "Counts and times only. A valid signature shows a file is unchanged since signing, not that it is true.",
        "sources": list(sources),
        "settings": {"seed": seed, "time_limit_s": config.c2pa_time_limit_s, "trust_list": None},
        "library": _library_versions(),
        "scan": _scan(dataset.items, config),
        "known_answers_on_real_images": known,
        "video": video,
        "changing_single_bytes": sweep,
        "limitations": list(LIMITATIONS),
    }


def _library_versions() -> dict[str, str]:
    import c2pa

    return {"c2pa_python": c2pa.__version__ if hasattr(c2pa, "__version__") else "unknown", "c2pa_rs": c2pa.sdk_version()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.media.eval.content_credentials", description=__doc__)
    parser.add_argument("--real", type=Path, required=True)
    parser.add_argument("--fake", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--source", action="append", required=True, help='as "name|licence|url"')
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--sample", type=int, default=100, help="how many images to sign and change")
    parser.add_argument("--flips", type=int, default=200, help="how many changed bytes to try in the video data")
    parser.add_argument("--large-video-mb", type=int, default=200)
    parser.add_argument("--sweep-step", type=int, default=23, help="change every Nth byte of a signed image")
    parser.add_argument("--video-sweep-step", type=int, default=1, help="change every Nth byte of a video's credentials")
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
    result = measure(
        args.real,
        args.fake,
        sources=sources,
        seed=args.seed,
        sample=args.sample,
        flips=args.flips,
        large_video_mb=args.large_video_mb,
        sweep_step=args.sweep_step,
        video_sweep_step=args.video_sweep_step,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{result['scan']['images']} images. Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
