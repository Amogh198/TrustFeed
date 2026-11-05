"""Measure the detector on labelled images. Run from the repository root.

    python -m backend.media.eval --real DIR --fake DIR --out data/eval/RESULT.json \
        --source "name|licence|url"

Subfolders become categories, such as DIR/face_swap. Images are only read, never copied.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from backend.media.classifier import HuggingFaceClassifier
from backend.media.config import DEFAULT_MODEL_ID, DEFAULT_MODEL_REVISION
from backend.media.eval.runner import ClassifierFactory, parse_model, parse_source, run_benchmark, write_result


def main(argv: list[str] | None = None, classifier_factory: ClassifierFactory = HuggingFaceClassifier) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.media.eval", description=__doc__)
    parser.add_argument("--real", type=Path, required=True, help="folder of images labelled real")
    parser.add_argument("--fake", type=Path, required=True, help="folder of images labelled fake")
    parser.add_argument("--out", type=Path, required=True, help="where to write the JSON results")
    parser.add_argument(
        "--source",
        action="append",
        required=True,
        help='where the images came from and their licence, as "name|licence|url". Repeat for each source.',
    )
    parser.add_argument(
        "--compare",
        action="append",
        default=[],
        metavar="ORG/NAME@COMMIT",
        help="another model to measure, pinned to a commit. Its weights must already be downloaded.",
    )
    parser.add_argument("--seed", type=int, default=0, help="changes which images go in which split")
    args = parser.parse_args(argv)

    for folder in (args.real, args.fake):
        if not folder.is_dir():
            print(f"error: not a folder: {folder}", file=sys.stderr)
            return 2
    try:
        sources = [parse_source(text) for text in args.source]
        models = [(DEFAULT_MODEL_ID, DEFAULT_MODEL_REVISION), *(parse_model(text) for text in args.compare)]
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    result = run_benchmark(
        args.real, args.fake, sources=sources, models=models, seed=args.seed, classifier_factory=classifier_factory
    )
    write_result(result, args.out)
    print(f"{result['dataset']['real']} real and {result['dataset']['fake']} fake images. Wrote {args.out}")
    for model in result["models"]:
        if model["status"] != "complete":
            print(f"{model['model_id']}: unavailable. {model['reason']}")
            continue
        measured = model["current_bands"]["all_images"]
        recall, false_positives = measured["recall"], measured["false_positive_rate"]
        print(
            f"{model['model_id']}: recall {recall['count']}/{recall['total']}, "
            f"false positives {false_positives['count']}/{false_positives['total']}, "
            f"inconclusive {measured['inconclusive_rate']['count']}/{measured['inconclusive_rate']['total']}"
        )
        if measured["too_few_to_conclude"]:
            print("  Too few images to conclude anything from these figures.")
    return 0 if any(model["status"] == "complete" for model in result["models"]) else 1


if __name__ == "__main__":
    sys.exit(main())
