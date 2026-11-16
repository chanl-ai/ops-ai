"""The pre-push lint reads what is pushed, not the working tree: another builder's unfinished file with a lint error
must not block a push of clean commits, and a lint error in a pushed commit must."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUFF = str(ROOT / ".venv/bin/ruff")
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True, env=GIT_ENV)
    return done.stdout.strip()


def push(repo: Path, since: str, to: str) -> subprocess.CompletedProcess[str]:
    refs = f"refs/heads/main {to} refs/heads/main {since}\n"
    env = {"PATH": "/usr/bin:/bin", "OPS_RUFF": RUFF, "HOME": str(repo)}
    return subprocess.run(
        ["sh", str(repo / ".githooks/pre-push")],
        cwd=repo,
        input=refs,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def make_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    (repo / ".githooks").mkdir(parents=True)
    (repo / ".githooks/pre-push").write_text((ROOT / ".githooks/pre-push").read_text())
    (repo / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n")
    (repo / "ok.py").write_text("x = 1\n")
    git(tmp_path, "init", "-q", str(repo))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    return repo, git(repo, "rev-parse", "HEAD")


def test_an_unfinished_file_in_the_tree_does_not_block_a_push_of_clean_commits(tmp_path: Path) -> None:
    repo, base = make_repo(tmp_path)
    (repo / "ok.py").write_text("x = 2\n")
    git(repo, "commit", "-qam", "clean")
    (repo / "other.py").write_text("import os,sys\n" + "y = " + "1" * 200 + "\n")
    done = push(repo, base, git(repo, "rev-parse", "HEAD"))
    assert done.returncode == 0, done.stdout + done.stderr


def test_a_lint_error_in_a_pushed_commit_blocks_the_push(tmp_path: Path) -> None:
    repo, base = make_repo(tmp_path)
    (repo / "bad.py").write_text("import os,sys\n")
    git(repo, "add", "bad.py")
    git(repo, "commit", "-qm", "bad")
    # The working tree is fixed after the commit, which the old hook would have read.
    (repo / "bad.py").write_text("x = 1\n")
    done = push(repo, base, git(repo, "rev-parse", "HEAD"))
    assert done.returncode != 0 and "pushed files" in done.stdout, done.stdout + done.stderr
