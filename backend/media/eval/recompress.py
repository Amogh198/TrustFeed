"""Make recompressed copies, like those a social platform produces, to test detector robustness.

    python -m backend.media.eval.recompress --in DIR --out DIR

Copies keep the folder layout, so the benchmark can compare them with the originals.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

MAX_SIDE = 800
QUALITY = 40
_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_REPO = Path(__file__).resolve().parents[3]


def recompress_tree(source: Path, target: Path, *, max_side: int = MAX_SIDE, quality: int = QUALITY) -> tuple[int, int]:
    """Return how many images were written, and how many could not be read."""
    written = failed = 0
    for path in sorted(p for p in source.rglob("*") if p.is_file() and p.suffix.casefold() in _SUFFIXES):
        destination = (target / path.relative_to(source)).with_suffix(".jpg")
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with Image.open(path) as image:
                copy = image.convert("RGB")
            copy.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            copy.save(destination, format="JPEG", quality=quality)
            written += 1
        except (OSError, ValueError, Image.DecompressionBombError):
            failed += 1
    return written, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.media.eval.recompress", description=__doc__)
    parser.add_argument("--in", dest="source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="folder for copies, outside the repository")
    args = parser.parse_args(argv)
    if args.out.resolve().is_relative_to(_REPO):
        print("error: images must stay outside the repository.", file=sys.stderr)
        return 2
    written, failed = recompress_tree(args.source, args.out)
    print(f"Wrote {written} copies. {failed} images could not be read.")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
