"""Command line for trying a search and recording one for replay.

    python -m backend.provenance search IMAGE          # local reference list only
    python -m backend.provenance search IMAGE --web    # sends the image to configured providers
    python -m backend.provenance record IMAGE --licence "CC0" --attribution "..."
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.provenance.models import Status
from backend.provenance.replay import DEFAULT_REPLAY_PATH, record_report
from backend.provenance.service import investigate_provenance


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.provenance", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    search = commands.add_parser("search", help="report where an image was found")
    search.add_argument("image", type=Path)
    search.add_argument("--web", action="store_true", help="send the image to configured search providers")
    search.add_argument("--module-only", action="store_true", help="print only the ModuleResult fields")

    record = commands.add_parser("record", help="run a real web search and save it for replay")
    record.add_argument("image", type=Path)
    record.add_argument("--licence", required=True, help="the image's licence, which must allow this use")
    record.add_argument("--attribution", required=True, help="where the image came from and who made it")
    record.add_argument("--out", type=Path, default=DEFAULT_REPLAY_PATH)

    args = parser.parse_args(argv)
    if args.command == "search":
        report = investigate_provenance(args.image, search_web=args.web)
        payload = report.to_module_result() if args.module_only else report.model_dump(mode="json")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if report.status is not Status.UNAVAILABLE else 2

    report = investigate_provenance(args.image, search_web=True)
    try:
        record_report(args.out, report, licence=args.licence, attribution=args.attribution)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        for line in report.limitations:
            print(f"  {line}", file=sys.stderr)
        return 2
    print(f"Recorded {len(report.appearances)} appearances to {args.out}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
