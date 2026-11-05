"""Run with: python -m pytest tools -q"""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("compat_check.py")


def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def commit_file(clone, branch, path, text, start="main"):
    git(clone, "switch", "-q", "-c", branch, start)
    (clone / path).write_text(text, encoding="utf-8")
    git(clone, "add", "-A")
    git(clone, "commit", "-qm", f"change {path}")
    git(clone, "push", "-q", "origin", branch)


@pytest.fixture
def repo(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True, capture_output=True)
    git(clone, "switch", "-q", "-c", "main")
    (clone / "shared.txt").write_text("base\n", encoding="utf-8")
    git(clone, "add", "-A")
    git(clone, "commit", "-qm", "base")
    git(clone, "push", "-q", "origin", "main")
    return clone


def check(cwd, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--no-tests", *args], cwd=cwd, capture_output=True, text=True, check=False
    )


def test_clean_branches_merge_and_missing_lanes_are_skipped(repo):
    commit_file(repo, "feat/a", "a.txt", "a\n")
    commit_file(repo, "feat/b", "b.txt", "b\n")
    result = check(repo)
    assert result.returncode == 0, result.stdout
    assert "PASS merged origin/feat/a" in result.stdout
    assert "PASS merged origin/feat/b" in result.stdout
    assert "SKIP T1 output accepted" in result.stdout


def test_conflicting_branches_are_reported_as_failure(repo):
    commit_file(repo, "feat/a", "shared.txt", "a\n")
    commit_file(repo, "feat/b", "shared.txt", "b\n")
    result = check(repo)
    assert result.returncode == 1
    assert "FAIL merge conflict in origin/feat/b: shared.txt" in result.stdout


def test_nothing_changes_in_the_checkout_or_remote(repo):
    commit_file(repo, "feat/a", "a.txt", "a\n")
    commit_file(repo, "feat/b", "b.txt", "b\n", start="main")

    def state(*args):
        return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout

    before = (state("rev-parse", "HEAD"), state("rev-parse", "origin/main"), state("status", "--short"))
    check(repo)
    assert (state("rev-parse", "HEAD"), state("rev-parse", "origin/main"), state("status", "--short")) == before
    assert state("worktree", "list").count("\n") == 1
    assert state("rev-parse", "origin/main") == state("ls-remote", "origin", "main").split()[0] + "\n"


def test_only_named_branches_are_included(repo):
    commit_file(repo, "feat/a", "a.txt", "a\n")
    commit_file(repo, "feat/b", "b.txt", "b\n")
    result = check(repo, "--branch", "feat/a")
    assert "origin/feat/a" in result.stdout
    assert "origin/feat/b" not in result.stdout


def test_outside_a_repository_fails_clearly(tmp_path):
    result = check(tmp_path)
    assert result.returncode == 1
    assert "inside the repository" in result.stdout
