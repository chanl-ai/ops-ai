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
    (repo / "pyproject.toml").write_text('[tool.ruff]\nline-length = 100\n[tool.ruff.lint]\nselect = ["E", "I"]\n')
    (repo / "ok.py").write_text("x = 1\n")
    git(tmp_path, "init", "-q", str(repo))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "base")
    return repo, git(repo, "rev-parse", "HEAD")


def test_first_party_import_next_to_a_third_party_one_in_order_pushes_cleanly(tmp_path: Path) -> None:
    # Ruff classifies an import as first party from the package folders on disk, so linting only the changed files
    # reported I001 on correctly sorted imports.
    repo, base = make_repo(tmp_path)
    (repo / "mypkg").mkdir()
    (repo / "mypkg/__init__.py").write_text("")
    (repo / "mypkg/core.py").write_text("y = 1\n")
    (repo / "mod.py").write_text("import yaml\n\nimport mypkg\n\nprint(yaml, mypkg)\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "first party")
    # Only mod.py changes after this base, so mypkg is absent from the changed files.
    base = git(repo, "rev-parse", "HEAD")
    (repo / "mod.py").write_text("import yaml\n\nimport mypkg\n\nprint(yaml, mypkg, 2)\n")
    git(repo, "commit", "-qam", "touch mod")
    done = push(repo, base, git(repo, "rev-parse", "HEAD"))
    assert done.returncode == 0, done.stdout + done.stderr


def test_an_uncommitted_lint_error_in_the_tree_does_not_block(tmp_path: Path) -> None:
    repo, base = make_repo(tmp_path)
    (repo / "ok.py").write_text("x = 2\n")
    git(repo, "commit", "-qam", "clean")
    (repo / "ok.py").write_text("import os,sys\n")
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


def test_a_real_push_runs_the_trees_hook_and_skips_an_unfinished_change_to_a_pushed_file(tmp_path: Path) -> None:
    # The installed hook was a copy made when hooks were last installed, so a fix to .githooks/pre-push never ran
    # until someone reinstalled. Installed while the tree's hook is still a stub that refuses every push, then given
    # the real hook: a push of clean commits passes although the same file carries an unfinished lint error.
    repo, _ = make_repo(tmp_path)
    (repo / "scripts").mkdir()
    (repo / "scripts/install-hooks.sh").write_text((ROOT / "scripts/install-hooks.sh").read_text())
    real = (repo / ".githooks/pre-push").read_text()
    (repo / ".githooks/pre-push").write_text("#!/bin/sh\n# ops-ai hook: an old copy\necho old hook ran; exit 1\n")
    for hook in ("pre-commit", "commit-msg"):
        (repo / f".githooks/{hook}").write_text("#!/bin/sh\nexit 0\n")
    subprocess.run(["sh", "scripts/install-hooks.sh"], cwd=repo, check=True, env={**GIT_ENV, "PATH": "/usr/bin:/bin"})
    (repo / ".githooks/pre-push").write_text(real)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "hooks")
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "-q", "--bare", str(remote))
    git(repo, "remote", "add", "origin", str(remote))
    env = {**GIT_ENV, "PATH": "/usr/bin:/bin", "OPS_RUFF": RUFF, "HOME": str(repo)}

    def real_push() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "push", "-q", "origin", "HEAD:main"], cwd=repo, capture_output=True, text=True, env=env, check=False
        )

    assert real_push().returncode == 0
    (repo / "ok.py").write_text("x = 3\n")
    git(repo, "commit", "-qam", "clean change")
    (repo / "ok.py").write_text("import os,sys\n" + "x = " + "1" * 200 + "\n")
    done = real_push()
    assert done.returncode == 0, done.stdout + done.stderr
    (repo / "ok.py").write_text("x = 4\n")
    (repo / "bad.py").write_text("import os,sys\n")
    git(repo, "add", "bad.py", "ok.py")
    git(repo, "commit", "-qm", "bad")
    done = real_push()
    assert done.returncode != 0 and "pushed files" in done.stdout + done.stderr, done.stdout + done.stderr
