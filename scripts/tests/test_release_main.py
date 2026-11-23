"""`make release-main` (scripts/release-main.sh) on scratch repositories, by failure mode: main moves to a commit it is
not an ancestor of (a force in disguise); a refused push leaves the owner no command; a rerun after the owner pushed
fails instead of finishing; a dry run moves main."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "release-main.sh"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name)
    git(repo, "add", name)
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--no-verify", "-m", name)
    return git(repo, "rev-parse", "HEAD")


def main_script(repo: Path, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(SCRIPT)], cwd=repo, capture_output=True, text=True, env={**os.environ, **env}, check=False
    )


def clone_pair(tmp: Path) -> tuple[Path, Path]:
    remote, work = tmp / "remote.git", tmp / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True, capture_output=True)
    commit(work, "a")
    git(work, "push", "-q", "origin", "HEAD:main")
    return remote, work


def test_main_fast_forwards_to_the_develop_commit_and_a_rerun_changes_nothing(tmp_path: Path) -> None:
    remote, work = clone_pair(tmp_path)
    head = commit(work, "b")
    assert main_script(work, DRY="1").returncode == 0 and git(remote, "rev-parse", "main") != head
    done = main_script(work)
    assert done.returncode == 0 and git(remote, "rev-parse", "main") == head
    assert "already at" in main_script(work).stdout


def test_main_is_never_moved_to_a_commit_that_does_not_contain_it(tmp_path: Path) -> None:
    remote, work = clone_pair(tmp_path)
    git(work, "checkout", "-q", "-b", "side", "HEAD~0")
    side = commit(work, "side")
    git(work, "push", "-q", "origin", "side:main")
    git(work, "reset", "-q", "--hard", "HEAD~1")
    other = commit(work, "other")
    refused = main_script(work)
    assert refused.returncode == 1 and "not a fast-forward" in refused.stderr
    assert git(remote, "rev-parse", "main") == side != other


def test_a_refused_push_prints_the_one_command_for_the_owner_and_exits_3(tmp_path: Path) -> None:
    remote, work = clone_pair(tmp_path)
    head = commit(work, "b")
    hook = remote / "hooks/pre-receive"
    hook.write_text("#!/bin/sh\necho 'protected branch' >&2\nexit 1\n")
    hook.chmod(0o755)
    done = main_script(work)
    assert done.returncode == 3
    assert f"git push origin {head}:main" in done.stderr
    assert git(remote, "rev-parse", "main") != head


def test_the_push_goes_to_push_url_when_one_is_set(tmp_path: Path) -> None:
    remote, work = clone_pair(tmp_path)
    head = commit(work, "b")
    other = tmp_path / "other.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(remote), str(other)], check=True)
    done = main_script(work, PUSH_URL=str(other))
    assert done.returncode == 0 and git(other, "rev-parse", "main") == head
    assert git(remote, "rev-parse", "main") != head
