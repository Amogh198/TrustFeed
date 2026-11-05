#!/usr/bin/env python3
"""Check that all agents' branches work together, without merging anything for real.

    python tools/compat_check.py                     # every feature branch
    python tools/compat_check.py --branch feat/a     # only the named branches
    python tools/compat_check.py --no-tests          # conflicts and contracts only

It merges the branches in a temporary worktree, checks the contracts between
lanes, runs each lane's tests, then deletes the worktree. Your checkout, branches
and the remote are not changed. Missing packages make a check SKIP, not FAIL, so
install the requirements of each lane for full coverage.

PASS: compatible. OPEN: planned wiring not done yet. SKIP: couldn't check.
FAIL: a real conflict or incompatibility. Exit code 1 means a FAIL occurred.
"""

from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BASE_REF = "origin/main"
TEST_SUITES = {
    "T1 media": "backend/media/tests",
    "T2 network": "backend/network/tests",
    "T3 API": "backend/api/tests",
    "T1 source search": "backend/provenance/tests",
    "Coordination tools": "tools",
}
TEST_TIMEOUT_SECONDS = 300
# Merges in the temporary worktree need an identity but are never pushed.
_MERGE_IDENTITY = ("-c", "user.name=compat-check", "-c", "user.email=compat-check@example.invalid")

_CONTRACT_PROBE = r'''
import re
import tempfile
from pathlib import Path


def check(name, function):
    try:
        print(f"{function() or 'PASS'} {name}")
    except ModuleNotFoundError as error:
        print(f"SKIP {name}: {error.name} is not available")
    except Exception as error:
        print(f"FAIL {name}: {type(error).__name__}: {str(error)[:300]}")


def t1_output_matches_t3():
    from PIL import Image
    from backend.api.app.models import ModuleResult
    from backend.media import analyze_media
    with tempfile.TemporaryDirectory() as folder:
        image = Path(folder) / "probe.png"
        Image.new("RGB", (64, 64), (120, 40, 200)).save(image)
        ModuleResult(**analyze_media(str(image)).to_module_result())
        ModuleResult(**analyze_media(str(Path(folder) / "missing.png")).to_module_result())


def t2_output_matches_t3():
    from pydantic import TypeAdapter
    from backend.api.app.models import ModuleResult
    from backend.network import get_network_module_result, get_network_payload
    ModuleResult(**get_network_module_result("demo-001"))
    TypeAdapter(dict[str, list[dict[str, object]]]).validate_python(get_network_payload("demo-001"))


def client():
    from fastapi.testclient import TestClient
    from backend.api.app.main import app
    return TestClient(app)


def t3_responses_match_contract():
    api = client()
    assert api.get("/health").status_code == 200, "/health did not return 200"
    response = api.post("/api/cases/analyze", json={"text": "A sample claim to analyze."})
    assert response.status_code == 200, f"analyze returned {response.status_code}"
    body = response.json()
    expected = {"case_id", "created_at", "overall_risk", "summary", "modules", "uncertainties", "recommended_actions"}
    assert expected <= set(body), f"missing fields: {sorted(expected - set(body))}"
    assert body["overall_risk"] in {"low", "moderate", "high", "critical", "inconclusive"}, body["overall_risk"]
    assert {"text", "media", "network"} <= set(body["modules"]), f"modules: {sorted(body['modules'])}"
    for name, module in body["modules"].items():
        fields = {"status", "score", "confidence", "evidence", "limitations"}
        assert fields <= set(module), f"{name} is missing {sorted(fields - set(module))}"
    network = api.get(f"/api/network/{body['case_id']}").json()
    assert set(network) == {"nodes", "edges", "timeline"}, f"network keys: {sorted(network)}"
    assert api.get("/api/cases/unknown-case").status_code == 404, "unknown case did not return 404"


def t2_wired_into_t3():
    if client().get("/api/network/demo-001").status_code != 200:
        return "OPEN"


def t1_wired_into_t3():
    body = client().post("/api/cases/analyze", json={"text": "A sample claim to analyze."}).json()
    limitations = " ".join(body["modules"]["media"]["limitations"])
    if "not integrated" in limitations:
        return "OPEN"


def t4_uses_t3():
    client_file = Path("frontend/src/api.js")
    if not client_file.is_file():
        raise ModuleNotFoundError(name="frontend/src/api.js on any branch")
    from backend.api.app.main import app
    served = {re.sub(r"[{][^}]*[}]", "{}", route.path) for route in app.routes}
    called = re.findall(r"[(][`']([^`']*/(?:api/|health)[^`']*)[`']", client_file.read_text(encoding="utf-8"))
    called = {re.sub(r"[?].*", "", re.sub(r"[$][{].*?[}]", "{}", path)).rstrip("{}") or path for path in called}
    missing = [path for path in called if not any(route.startswith(path) for route in served)]
    assert called, "no API calls were found in frontend/src/api.js"
    assert not missing, f"the frontend calls routes the API does not serve: {missing}"


check("T1 output accepted by T3 ModuleResult", t1_output_matches_t3)
check("T2 output accepted by T3 ModuleResult and network route type", t2_output_matches_t3)
check("T3 responses match API_CONTRACTS.md, as T4 expects", t3_responses_match_contract)
check("T2 demo network reachable through T3 route", t2_wired_into_t3)
check("T1 media analysis wired into T3", t1_wired_into_t3)
check("T4 calls only routes that T3 serves", t4_uses_t3)
'''


def run(command: list[str], cwd: Path, timeout: int = 60, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        env=env,
        stdin=subprocess.DEVNULL,
    )


def feature_branches(root: Path) -> list[str]:
    output = run(["git", "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"], root).stdout
    return sorted(
        ref
        for ref in output.split()
        if ref.startswith("origin/") and ref not in ("origin/HEAD", BASE_REF) and not ref.startswith("origin/status/")
    )


def merge_branches(worktree: Path, branches: list[str]) -> list[str]:
    """Merge each branch in turn, and return conflicts. A conflicting branch is left out."""
    conflicts = []
    for branch in branches:
        merged = run(["git", *_MERGE_IDENTITY, "merge", "--no-edit", "--no-ff", branch], worktree)
        if merged.returncode == 0:
            print(f"PASS merged {branch}")
            continue
        files = run(["git", "diff", "--name-only", "--diff-filter=U"], worktree).stdout.split()
        run(["git", "merge", "--abort"], worktree)
        detail = ", ".join(files) or merged.stderr.strip()[:200]
        print(f"FAIL merge conflict in {branch}: {detail}")
        conflicts.append(branch)
    return conflicts


def run_contract_checks(worktree: Path, env: dict[str, str]) -> list[str]:
    try:
        probe = run([sys.executable, "-c", _CONTRACT_PROBE], worktree, timeout=TEST_TIMEOUT_SECONDS, env=env)
    except subprocess.TimeoutExpired:
        print("FAIL contract checks timed out")
        return ["FAIL"]
    lines = [line for line in probe.stdout.splitlines() if line.split(" ", 1)[0] in ("PASS", "FAIL", "OPEN", "SKIP")]
    for line in lines:
        print(line)
    if probe.returncode != 0:
        print(f"FAIL contract checks crashed: {probe.stderr.strip()[-300:]}")
        lines.append("FAIL")
    return lines


def run_test_suites(worktree: Path, env: dict[str, str]) -> list[str]:
    results = []
    for lane, path in TEST_SUITES.items():
        if not (worktree / path).exists():
            print(f"SKIP {lane} tests: {path} is not on any merged branch")
            continue
        command = [sys.executable, "-m", "pytest", path, "-q", "--no-header", "-p", "no:cacheprovider"]
        try:
            done = run(command, worktree, timeout=TEST_TIMEOUT_SECONDS, env=env)
        except subprocess.TimeoutExpired:
            print(f"FAIL {lane} tests: timed out after {TEST_TIMEOUT_SECONDS} seconds")
            results.append("FAIL")
            continue
        last = (done.stdout.strip().splitlines() or [done.stderr.strip()[-200:]])[-1]
        outcome = "PASS" if done.returncode == 0 else "FAIL"
        print(f"{outcome} {lane} tests: {last}")
        results.append(outcome)
    return results


def main(argv: list[str] | None = None) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(description="Check that all agents' branches work together.")
    parser.add_argument("--branch", action="append", default=[], help="branch to include; repeatable")
    parser.add_argument("--no-tests", action="store_true", help="skip each lane's test suite")
    parser.add_argument("--no-fetch", action="store_true", help="use refs already fetched")
    args = parser.parse_args(argv)

    top = run(["git", "rev-parse", "--show-toplevel"], Path.cwd())
    if top.returncode != 0:
        print("FAIL run this inside the repository")
        return 1
    root = Path(top.stdout.strip())

    if not args.no_fetch and run(["git", "fetch", "origin", "--prune", "--quiet"], root).returncode != 0:
        print("SKIP git fetch failed, so remote branches may be out of date")
    branches = [f"origin/{name.removeprefix('origin/')}" for name in args.branch] or feature_branches(root)
    print(f"Temporary merge of {BASE_REF} with {len(branches)} branch(es). Nothing is pushed.")

    holder = Path(tempfile.mkdtemp(prefix="trustfeed-compat-"))
    worktree = holder / "merged"
    added = run(["git", "worktree", "add", "--quiet", "--detach", str(worktree), BASE_REF], root)
    if added.returncode != 0:
        print(f"FAIL could not create worktree: {added.stderr.strip()[:300]}")
        shutil.rmtree(holder, ignore_errors=True)
        return 1

    try:
        conflicts = merge_branches(worktree, branches)
        env = {**os.environ, "PYTHONPATH": str(worktree), "PYTHONDONTWRITEBYTECODE": "1"}
        contracts = run_contract_checks(worktree, env)
        tests = [] if args.no_tests else run_test_suites(worktree, env)
    finally:
        run(["git", "worktree", "remove", "--force", str(worktree)], root)
        run(["git", "worktree", "prune"], root)
        shutil.rmtree(holder, ignore_errors=True)

    failed = bool(conflicts) or any(line.startswith("FAIL") for line in [*contracts, *tests])
    print("compatibility check failed" if failed else "compatibility check passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
