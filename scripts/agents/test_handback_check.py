"""One test per hand-back refusal, plus the pass, against real git repositories (origin, main checkout, worktree)."""

import json
import os
import subprocess
from pathlib import Path

import handback_check
import pytest

BRANCH = "feat/x"


def run(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def repos(tmp_path: Path) -> tuple[Path, Path]:
    """A bare origin, the main checkout on develop, and a builder worktree on BRANCH with one pushed commit."""
    origin, main, wt = tmp_path / "origin.git", tmp_path / "main", tmp_path / "wt"
    run(tmp_path, "init", "-q", "--bare", str(origin))
    run(tmp_path, "init", "-q", "-b", "develop", str(main))
    config = {"user.email": "b@example.com", "user.name": "b", "commit.gpgsign": "false", "core.hooksPath": "/dev/null"}
    for k, v in config.items():
        run(main, "config", k, v)
    (main / "a.txt").write_text("a\n")
    run(main, "add", "a.txt")
    run(main, "commit", "-q", "-m", "base")
    run(main, "remote", "add", "origin", str(origin))
    run(main, "push", "-q", "origin", "develop")
    run(main, "worktree", "add", "-q", "-b", BRANCH, str(wt))
    (wt / "b.txt").write_text("b\n")
    run(wt, "add", "b.txt")
    run(wt, "commit", "-q", "-m", "change")
    run(wt, "push", "-q", "origin", BRANCH)
    return main, wt


def test_refuses_a_clean_pushed_worktree_still_on_disk(repos: tuple[Path, Path]) -> None:
    main, wt = repos
    ok, line = handback_check.check(main, BRANCH)
    assert not ok and "still there" in line and f"git worktree remove {wt}" in line


def test_refuses_uncommitted_files(repos: tuple[Path, Path]) -> None:
    main, wt = repos
    (wt / "c.txt").write_text("c\n")
    ok, line = handback_check.check(main, BRANCH)
    assert not ok and "uncommitted" in line


def test_refuses_commits_origin_lacks(repos: tuple[Path, Path]) -> None:
    main, wt = repos
    (wt / "b.txt").write_text("b2\n")
    run(wt, "commit", "-q", "-am", "more")
    run(main, "worktree", "remove", str(wt))
    ok, line = handback_check.check(main, BRANCH)
    assert not ok and "push the local commits" in line


def test_refuses_a_running_preview(repos: tuple[Path, Path]) -> None:
    main, wt = repos
    run(main, "worktree", "remove", str(wt))
    (main / ".run" / "previews").mkdir(parents=True)
    (main / ".run" / "previews" / "x.json").write_text(json.dumps({"branch": BRANCH, "offset": 38000}))
    (main / ".run" / "offset-38000").mkdir()
    (main / ".run" / "offset-38000" / "console.pid").write_text(str(os.getpid()))
    ok, line = handback_check.check(main, BRANCH)
    assert not ok and "make wt-stop" in line


def test_passes_once_pushed_and_removed_and_the_branch_is_kept(repos: tuple[Path, Path]) -> None:
    main, wt = repos
    run(main, "worktree", "remove", str(wt))
    ok, line = handback_check.check(main, BRANCH)
    assert ok, line
    assert not wt.exists()
    run(main, "rev-parse", "--verify", f"refs/heads/{BRANCH}")
