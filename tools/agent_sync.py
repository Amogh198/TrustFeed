#!/usr/bin/env python3
"""Read-only coordination view across all agents' remote branches.

    python tools/agent_sync.py                 # one-screen team board
    python tools/agent_sync.py show amogh      # one agent's full status record
    python tools/agent_sync.py check bhuvan    # validate before pushing

Status files are committed on each agent's own feature branch, so the copy on
main is usually behind. This tool finds the newest copy of each file on any
remote branch. It never writes to the repository or to GitHub.
Standard library only; `gh` is optional and adds the pull request list.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

STATUS_DIR = "agent-status"
BASE_REF = "origin/main"
FIELDS = (
    "AGENT",
    "RESPONSIBILITY",
    "BRANCH",
    "CURRENT TASK",
    "STATUS",
    "COMPLETED",
    "IN PROGRESS",
    "NEXT ACTION",
    "FILES OWNED",
    "LATEST COMMIT",
    "INTERFACES CHANGED",
    "DEPENDENCIES",
    "BLOCKERS",
    "LAST UPDATED",
    "PROTOCOL",
)
STATUS_VALUES = ("Ready", "Doing", "In Review", "Blocked", "Done")
MAX_VALUE_LENGTH = 240
# Changes here affect every lane, so they are always shown on the board.
SHARED_PATHS = (
    "API_CONTRACTS.md",
    "contracts/*",
    "AGENT_COORDINATION.md",
    "CLAUDE.md",
    "TASK_BOARD.md",
    "GITHUB_WORKFLOW.md",
    "COLLABORATION.md",
    ".claude/*",
    "tools/*",
    ".gitignore",
    ".env.example",
)
MAX_LINES_PER_SECTION = 8


def run(command: list[str], timeout: int = 15) -> str | None:
    """Return stdout, or None on any failure, so a hook can never block a session."""
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    try:
        done = subprocess.run(
            command,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=env,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def git(*args: str, timeout: int = 15) -> str | None:
    return run(["git", *args], timeout)


def remote_branches() -> list[str]:
    output = git("for-each-ref", "--format=%(refname:short)", "refs/remotes/origin") or ""
    return sorted(
        ref for ref in output.split() if ref.startswith("origin/") and ref != "origin/HEAD"
    )


def parse_record(text: str) -> dict[str, str]:
    record: dict[str, str] = {}
    for line in text.splitlines():
        name, separator, value = line.partition(":")
        if separator and name.strip() in FIELDS:
            record[name.strip()] = value.strip()
    return record


def validate_record(text: str) -> list[str]:
    problems = []
    names = [line.partition(":")[0].strip() for line in text.splitlines() if line.strip()]
    for field in FIELDS:
        count = names.count(field)
        if count != 1:
            problems.append(f"{field}: expected once, found {count}")
    problems.extend(f"unexpected line: {name[:40]!r}" for name in names if name not in FIELDS)

    record = parse_record(text)
    for field, value in record.items():
        if not value:
            problems.append(f"{field}: empty (write 'none' if nothing applies)")
        if len(value) > MAX_VALUE_LENGTH:
            problems.append(f"{field}: {len(value)} characters, limit is {MAX_VALUE_LENGTH}")
    if "STATUS" in record and record["STATUS"] not in STATUS_VALUES:
        problems.append(f"STATUS: must be one of {', '.join(STATUS_VALUES)}")
    if "LAST UPDATED" in record and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", record["LAST UPDATED"]):
        problems.append("LAST UPDATED: use YYYY-MM-DD")
    if "PROTOCOL" in record and not re.fullmatch(
        r"pending|adopted \d{4}-\d{2}-\d{2}", record["PROTOCOL"]
    ):
        problems.append("PROTOCOL: use 'pending' or 'adopted YYYY-MM-DD'")
    return problems


def owned_patterns(record: dict[str, str]) -> list[str]:
    return [item.strip() for item in record.get("FILES OWNED", "").split(",") if item.strip()]


def is_owned(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def is_shared(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in SHARED_PATHS)


def latest_records(branches: list[str]) -> dict[str, tuple[dict[str, str], str]]:
    """Map each agent to its newest status record and the branch holding it."""
    newest: dict[str, tuple[int, str, str]] = {}
    for branch in branches:
        listing = git("ls-tree", "--name-only", branch, f"{STATUS_DIR}/") or ""
        for path in listing.split("\n"):
            pure = PurePosixPath(path)
            if pure.suffix != ".md" or pure.name == "README.md":
                continue
            stamp = int((git("log", "-1", "--format=%ct", branch, "--", path) or "0").strip() or 0)
            current = newest.get(pure.stem)
            # On a tie, prefer main, which holds the merged copy.
            if current is None or stamp > current[0] or (stamp == current[0] and branch == BASE_REF):
                newest[pure.stem] = (stamp, branch, path)

    records = {}
    for agent, (_, branch, path) in sorted(newest.items()):
        text = git("show", f"{branch}:{path}")
        if text is not None:
            records[agent] = (parse_record(text), branch)
    return records


def changed_files(branch: str) -> list[str]:
    output = git("diff", "--name-only", f"{BASE_REF}...{branch}") or ""
    return [path for path in output.split("\n") if path and not path.startswith(f"{STATUS_DIR}/")]


def branch_agent(branch: str, records: dict[str, tuple[dict[str, str], str]]) -> str | None:
    short = branch.removeprefix("origin/")
    for agent, (record, _) in records.items():
        if short in re.split(r"[,\s]+", record.get("BRANCH", "")):
            return agent
    return None


def analyze_branches(
    branches: list[str], records: dict[str, tuple[dict[str, str], str]]
) -> tuple[list[str], list[str], list[str]]:
    """Return overlaps between branches, shared-file changes and ownership warnings."""
    touched: dict[str, list[str]] = {}
    shared: list[str] = []
    ownership: list[str] = []
    for branch in branches:
        if branch == BASE_REF:
            continue
        short = branch.removeprefix("origin/")
        files = changed_files(branch)
        author = branch_agent(branch, records)
        for path in files:
            touched.setdefault(path, []).append(short)
            if is_shared(path):
                shared.append(f"{path} on {short}")
                continue
            for agent, (record, _) in records.items():
                if agent != author and is_owned(path, owned_patterns(record)):
                    ownership.append(f"{short} changes {path}, owned by {agent}")
    overlaps = [
        f"{path}: {', '.join(names)}" for path, names in sorted(touched.items()) if len(names) > 1
    ]
    return overlaps, shared, ownership


def open_pull_requests() -> list[str] | None:
    output = run(
        ["gh", "pr", "list", "--state", "open", "--limit", "20", "--json",
         "number,title,headRefName,author,reviewDecision,isDraft"],
        timeout=15,
    )
    if output is None:
        return None
    lines = []
    for pull in sorted(json.loads(output), key=lambda item: item["number"]):
        state = "draft" if pull["isDraft"] else (pull["reviewDecision"] or "no review").lower()
        lines.append(
            f"#{pull['number']} {pull['title'][:70]} | {pull['headRefName']} | "
            f"{pull['author']['login']} | {state}"
        )
    return lines


def _section(title: str, lines: list[str]) -> None:
    if not lines:
        return
    print(f"{title}:")
    for line in lines[:MAX_LINES_PER_SECTION]:
        print(f"  {line}")
    if len(lines) > MAX_LINES_PER_SECTION:
        print(f"  ...and {len(lines) - MAX_LINES_PER_SECTION} more")


def command_board(args: argparse.Namespace) -> int:
    fetched = args.no_fetch or git("fetch", "origin", "--prune", "--quiet") is not None
    branches = remote_branches()
    records = latest_records(branches)

    print("AGENT BOARD. Protocol: AGENT_COORDINATION.md. Details: python tools/agent_sync.py show <agent>")
    if not fetched:
        print("WARNING: git fetch failed, so this may be out of date.")
    if not records:
        print("No agent-status files found on any remote branch.")
    for agent, (record, _) in records.items():
        print(
            f"{agent} | {record.get('STATUS', '?')} | {record.get('CURRENT TASK', '?')} | "
            f"blockers: {record.get('BLOCKERS', '?')} | updated {record.get('LAST UPDATED', '?')} | "
            f"protocol {record.get('PROTOCOL', '?')}"
        )

    overlaps, shared, ownership = analyze_branches(branches, records)
    _section("Branches", [branch.removeprefix("origin/") for branch in branches])
    if not args.no_prs:
        pulls = open_pull_requests()
        _section("Open PRs", ["unavailable (gh missing, offline or not logged in)"] if pulls is None else pulls)
    _section("Same file on several branches", overlaps)
    _section("Shared-file changes", shared)
    _section("Ownership warnings", ownership)
    return 0


def command_show(args: argparse.Namespace) -> int:
    git("fetch", "origin", "--prune", "--quiet")
    entry = latest_records(remote_branches()).get(args.agent)
    if entry is None:
        print(f"No status file found for {args.agent!r}.")
        return 1
    record, branch = entry
    print(f"[newest copy is on {branch}]")
    for field in FIELDS:
        print(f"{field}: {record.get(field, '(missing)')}")
    return 0


def command_check(args: argparse.Namespace) -> int:
    root = Path((git("rev-parse", "--show-toplevel") or ".").strip())
    status_path = root / STATUS_DIR / f"{args.agent}.md"
    if not status_path.exists():
        print(f"FAIL: {status_path.name} does not exist in {STATUS_DIR}/.")
        return 1

    text = status_path.read_text(encoding="utf-8")
    problems = validate_record(text)
    record = parse_record(text)

    changed = set(changed_files("HEAD"))
    changed.update(path for path in (git("diff", "--name-only", "HEAD") or "").split("\n") if path)
    changed.update((git("ls-files", "--others", "--exclude-standard") or "").split("\n"))
    changed = {path for path in changed if path and not path.startswith(f"{STATUS_DIR}/")}

    mine = owned_patterns(record)
    others = {
        agent: owned_patterns(item)
        for agent, (item, _) in latest_records(remote_branches()).items()
        if agent != args.agent
    }
    notices = []
    for path in sorted(changed):
        if is_owned(path, mine):
            continue
        if is_shared(path):
            notices.append(f"shared file, coordinate and notify affected lanes: {path}")
            continue
        owner = next((agent for agent, patterns in others.items() if is_owned(path, patterns)), None)
        problems.append(
            f"{path} is owned by {owner}" if owner else f"{path} has no owner; agree on one before pushing"
        )
    for path in (git("diff", "--name-only", f"{BASE_REF}...HEAD") or "").split("\n"):
        if path.startswith(f"{STATUS_DIR}/") and path != f"{STATUS_DIR}/{args.agent}.md":
            notices.append(f"another agent's status file changed: {path}")

    for notice in notices:
        print(f"NOTE: {notice}")
    for problem in problems:
        print(f"FAIL: {problem}")
    print("check failed" if problems else "check passed")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        # A Windows console encoding must not crash the tool on a teammate's PR title.
        sys.stdout.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(description="Read-only view of all agents' coordination state.")
    parser.add_argument("--no-fetch", action="store_true", help="use refs already fetched")
    parser.add_argument("--no-prs", action="store_true", help="skip the GitHub pull request lookup")
    parser.set_defaults(func=command_board)
    commands = parser.add_subparsers(dest="command")
    show = commands.add_parser("show", help="print one agent's full status record")
    show.add_argument("agent")
    show.set_defaults(func=command_show)
    check = commands.add_parser("check", help="validate your status file and changed-file ownership")
    check.add_argument("agent")
    check.set_defaults(func=command_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
