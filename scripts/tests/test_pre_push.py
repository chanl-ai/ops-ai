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
    env = {"PATH": "/usr/bin:/bin", "OPS_RUFF": RUFF, "HOME": str(repo), "OPS_FULL_HOOK": "1"}
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


ZERO = "0" * 40


def console_push(repo: Path, tmp_path: Path, local: str, _since: str) -> tuple[int, str, bool]:
    """Pushes `local` as a new branch through the hook with a `node` that records that the console suite ran and fails;
    returns the exit status, the output and whether the suite ran."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    ran = tmp_path / "suite-ran"
    # Installed dependencies are present, so the hook gets as far as running the suite.
    (repo / "node_modules").mkdir(exist_ok=True)
    (repo / "apps/console/node_modules").mkdir(parents=True, exist_ok=True)
    (bin_dir / "node").write_text(f"#!/bin/sh\ntouch {ran}\nexit 1\n")
    (bin_dir / "node").chmod(0o755)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "OPS_RUFF": RUFF, "HOME": str(repo), "OPS_FULL_HOOK": "1"}
    done = subprocess.run(
        ["sh", str(repo / ".githooks/pre-push"), "origin"],
        cwd=repo,
        input=f"refs/heads/release/1.0.0 {local} refs/heads/release/1.0.0 {ZERO}\n",
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return done.returncode, done.stdout + done.stderr, ran.exists()


def console_repo(tmp_path: Path, change: str) -> tuple[Path, str, str]:
    """A repo whose origin/main is the base and whose origin/develop holds one console change on top of it."""
    repo, base = make_repo(tmp_path)
    git(repo, "update-ref", "refs/remotes/origin/main", base)
    (repo / "apps/console/src").mkdir(parents=True)
    (repo / "apps/console/src/a.ts").write_text("export const a = 1\n")
    (repo / "bad.py").write_text(change)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "console change")
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "update-ref", "refs/remotes/origin/develop", head)
    return repo, base, head


def test_a_new_branch_at_a_commit_the_remote_has_skips_the_console_suite(tmp_path: Path) -> None:
    repo, _, head = console_repo(tmp_path, "x = 1\n")
    status, out, ran = console_push(repo, tmp_path, head, head)
    assert (status, ran) == (0, False) and "already on origin" in out, out


def test_a_commit_the_remote_lacks_runs_the_console_suite(tmp_path: Path) -> None:
    repo, _, head = console_repo(tmp_path, "x = 1\n")
    (repo / "apps/console/src/a.ts").write_text("export const a = 2\n")
    git(repo, "commit", "-qam", "one new commit")
    status, out, ran = console_push(repo, tmp_path, git(repo, "rev-parse", "HEAD"), head)
    assert (status, ran) == (1, True) and "console unit suite failed" in out, out


def test_commits_the_remote_has_are_still_linted(tmp_path: Path) -> None:
    repo, base, head = console_repo(tmp_path, "import os,sys\n")
    status, out, ran = console_push(repo, tmp_path, head, base)
    assert (status, ran) == (1, False) and "pushed files" in out, out


def test_a_console_push_from_a_worktree_without_node_modules_names_the_missing_install(tmp_path: Path) -> None:
    # A bare "test failed" from node --test reads as a real red suite; the hook must name the missing install instead.
    repo, base = make_repo(tmp_path)
    (repo / "apps/console/src").mkdir(parents=True)
    (repo / "apps/console/src/a.ts").write_text("export const a = 1\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "console change")
    done = push(repo, base, git(repo, "rev-parse", "HEAD"))
    out = done.stdout + done.stderr
    assert done.returncode != 0 and "pre-push: this worktree has no node_modules" in out and "pnpm install" in out, out
    assert "console unit suite failed" not in out, out


def push_to(repo: Path, since: str, to: str, branch: str) -> subprocess.CompletedProcess[str]:
    refs = f"refs/heads/x {to} refs/heads/{branch} {since}\n"
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


def test_a_remote_branch_named_for_the_process_is_refused_and_a_named_change_pushes(tmp_path: Path) -> None:
    repo, base = make_repo(tmp_path)
    refused = [push_to(repo, base, base, b) for b in ("lane/ui", "fix/console-fixes", "feat/Agents-Page", "wip")]
    assert all(r.returncode == 1 and "must be <type>/<scope>" in r.stdout for r in refused), [r.stdout for r in refused]
    ok = push_to(repo, base, base, "fix/console-slash-skill-chip")
    assert ok.returncode == 0, ok.stdout
