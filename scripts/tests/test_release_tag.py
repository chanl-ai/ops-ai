"""`make release-tag` (scripts/release-tag.sh) on scratch repositories, by failure mode: a release merge is tagged with
the wrong version or not at all; a rerun on the same merge changes the tag; a commit that is no release merge gets a
tag; a tag already naming another commit is moved instead of refused; a dry run makes a tag."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "release-tag.sh"
RELEASE = "Merge pull request #7 from chanl-ai/release/1.2.0"
HOTFIX = "Merge pull request #9 from chanl-ai/hotfix/1.2.1"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def tag(repo: Path, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(SCRIPT)], cwd=repo, capture_output=True, text=True, env={**os.environ, **env}, check=False
    )


def commit(repo: Path, name: str, message: str | None = None) -> str:
    (repo / name).write_text(name)
    git(repo, "add", name)
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--no-verify", "-m", message or name)
    return git(repo, "rev-parse", "HEAD")


def clone_pair(tmp: Path) -> tuple[Path, Path]:
    """A bare remote and a clone of it with one commit pushed."""
    remote, work = tmp / "remote.git", tmp / "work"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True, capture_output=True)
    commit(work, "a")
    git(work, "push", "-q", "origin", "HEAD:main")
    return remote, work


def test_a_release_or_hotfix_merge_is_tagged_with_its_branch_version_and_the_tag_is_pushed(tmp_path: Path) -> None:
    remote, work = clone_pair(tmp_path)
    release = commit(work, "b", RELEASE)
    assert tag(work).returncode == 0
    hotfix = commit(work, "c", HOTFIX)
    assert tag(work).returncode == 0
    assert git(remote, "rev-list", "-n", "1", "v1.2.0") == release
    assert git(remote, "rev-list", "-n", "1", "v1.2.1") == hotfix


def test_a_rerun_keeps_the_tag_and_a_tag_on_another_commit_is_never_moved(tmp_path: Path) -> None:
    remote, work = clone_pair(tmp_path)
    release = commit(work, "b", RELEASE)
    tag(work)
    assert "already v1.2.0" in tag(work).stdout
    commit(work, "c", RELEASE)
    moved = tag(work)
    assert moved.returncode == 1 and "never moved" in moved.stderr
    assert git(remote, "rev-list", "-n", "1", "v1.2.0") == release


def test_a_commit_that_is_no_release_merge_gets_no_tag_and_a_dry_run_makes_none(tmp_path: Path) -> None:
    remote, work = clone_pair(tmp_path)
    commit(work, "b", "fix(api): something")
    assert "gets no tag" in tag(work).stdout
    commit(work, "c", "Merge pull request #8 from chanl-ai/feat/api-thing")
    assert "gets no tag" in tag(work).stdout
    commit(work, "d", RELEASE)
    assert "next is v1.2.0" in tag(work, DRY="1").stdout
    assert git(remote, "tag", "--list") == "" and git(work, "tag", "--list") == ""
