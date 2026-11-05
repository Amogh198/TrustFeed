"""Watch a topic from the command line: ``python -m backend.network.watch --help``."""

import argparse
import time
from pathlib import Path
from typing import Any

from backend.network.monitor import Monitor

# Public services are shared, so this never polls faster than once a minute.
_MIN_INTERVAL_SECONDS = 60


def _print_snapshot(snapshot: dict[str, Any]) -> None:
    print(f"Poll {snapshot['poll']} at {snapshot['polled_at']}: {snapshot['total_matching_posts']} matching posts in total")
    for item in snapshot["platforms"]:
        print(f"  {item['label']}: {item['status']}, {snapshot['new_posts'][item['platform']]} new")
        for note in item["notes"]:
            print(f"    {note}")
    for alert in snapshot["alerts"]:
        print(f"  ALERT {alert['type']}: {alert['message']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Watch public platforms for a topic.")
    parser.add_argument("--watch-id", required=True)
    parser.add_argument("--text")
    parser.add_argument("--url", action="append", default=[], help="a link to watch; can be repeated")
    parser.add_argument("--hashtag", action="append", default=[], help="a hashtag to watch; can be repeated")
    parser.add_argument("--polls", type=int, default=1)
    parser.add_argument("--interval", type=int, default=300, help=f"seconds between polls, at least {_MIN_INTERVAL_SECONDS}")
    parser.add_argument(
        "--state",
        type=Path,
        help="keep results here between runs; this holds real people's public posts, so keep it out of Git",
    )
    args = parser.parse_args(argv)

    monitor = Monitor(args.watch_id, text=args.text, urls=tuple(args.url), hashtags=tuple(args.hashtag), state_path=args.state)
    for number in range(args.polls):
        if number:
            time.sleep(max(args.interval, _MIN_INTERVAL_SECONDS))
        _print_snapshot(monitor.poll())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
