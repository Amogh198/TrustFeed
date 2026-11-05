"""Command line for demos and manual checks. Run from the repository root."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from backend.media.analyzer import analyze_media
from backend.media.classifier import default_classifier, download_model
from backend.media.config import MediaConfig
from backend.media.errors import HashIndexUnavailable, MediaInputError
from backend.media.heatmap import occlusion_heatmap, render_overlay
from backend.media.metadata import read_image
from backend.media.models import CheckStatus
from backend.media.panel import download_panel
from backend.media.phash import JsonHashIndex, ReferenceEntry, compute_phash

_REPO = Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m backend.media")
    commands = parser.add_subparsers(dest="command", required=True)

    analyze = commands.add_parser("analyze", help="analyze an image or video and print JSON")
    analyze.add_argument("file", type=Path)
    analyze.add_argument("--index", type=Path, help="pHash reference index (JSON)")
    analyze.add_argument("--module-only", action="store_true", help="print only the contract-shaped result")
    analyze.add_argument("--panel", action="store_true", help="also run every detector on the panel (slow on CPU)")

    add = commands.add_parser("index-add", help="add an image to a pHash reference index")
    add.add_argument("file", type=Path)
    add.add_argument("--index", type=Path, required=True)
    add.add_argument("--label", required=True)
    add.add_argument("--first-seen")
    add.add_argument("--source")

    heatmap = commands.add_parser("heatmap", help="show where the model's score changes across an image")
    heatmap.add_argument("file", type=Path)
    heatmap.add_argument("--out", type=Path, required=True, help="PNG holding the image, outside the repository")

    commands.add_parser("download-model", help="download the classifier's safetensors weights")
    commands.add_parser("download-panel", help="download every panel detector's safetensors weights (about 2.3 GB)")
    return parser


def _heatmap(args: argparse.Namespace, config: MediaConfig) -> int:
    if args.out.resolve().is_relative_to(_REPO):
        print("error: this picture holds the image, so it must stay outside the repository.", file=sys.stderr)
        return 2
    try:
        image, _, _ = read_image(args.file, config)
    except MediaInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = occlusion_heatmap(image, default_classifier(config), batch_size=config.batch_size)
    print(json.dumps(result.model_dump(mode="json", exclude={"changes"}), indent=2))
    if result.status is not CheckStatus.COMPLETE:
        return 1
    args.out.write_bytes(render_overlay(image, result))
    return 0


def _analyze(args: argparse.Namespace, config: MediaConfig) -> int:
    if args.index:
        config = replace(config, phash_index_path=args.index)
    result = analyze_media(args.file, config=config, run_panel=args.panel)
    output = result.to_module_result() if args.module_only else result.model_dump(mode="json")
    print(json.dumps(output, indent=2))
    return 2 if result.failure_code else 0


def _index_add(args: argparse.Namespace, config: MediaConfig) -> int:
    try:
        index = JsonHashIndex.load(args.index) if args.index.exists() else JsonHashIndex()
        image, _, _ = read_image(args.file, config)
    except (HashIndexUnavailable, MediaInputError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    phash = compute_phash(image)
    index.add(ReferenceEntry(phash=phash, label=args.label, first_seen=args.first_seen, source=args.source))
    index.save(args.index)
    print(f"added {phash} ({len(index)} references)")
    return 0


def _download_model(config: MediaConfig) -> int:
    try:
        location = download_model(config)
    except Exception as exc:
        print(f"error: model download failed ({type(exc).__name__})", file=sys.stderr)
        return 1
    print(f"model ready: {location}")
    return 0


def _download_panel(config: MediaConfig) -> int:
    try:
        locations = download_panel(config)
    except Exception as exc:
        print(f"error: model download failed ({type(exc).__name__})", file=sys.stderr)
        return 1
    print(f"{len(locations)} models ready")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = MediaConfig.from_env()
    if args.command == "download-panel":
        return _download_panel(config)
    if args.command == "analyze":
        return _analyze(args, config)
    if args.command == "index-add":
        return _index_add(args, config)
    if args.command == "heatmap":
        return _heatmap(args, config)
    return _download_model(config)


if __name__ == "__main__":
    raise SystemExit(main())
