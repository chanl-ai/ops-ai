"""`make release-tag` (scripts/release-tag.sh, c-510) on scratch repositories, by failure mode: the day's number does
not count up; a rerun on the same merge makes a second tag; the tag is made but never pushed; a merge that loses a race
for a number fails instead of taking the next one; a dry run makes a tag."""

from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "release-tag.sh"
DAY = datetime.now(UTC).strftime("%Y-%m-%d")


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def tag(repo: Path, **env: str) -> str:
    run = subprocess.run(
        ["sh", str(SCRIPT)], cwd=repo, capture_output=True, text=True, env={**os.environ, **env}, check=True
    )
    return run.stdout.strip()


def commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name)
    git(repo, "add", name)
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--no-verify", "-m", name)
    return git(repo, "rev-parse", "HEAD")


def clone_pair(tmp: Path) -> tuple[Path, Path]:
    """A bare remote and a clone of it with one commit pushed."""
    remote, work = tmp / "remote.git", tmp / "work"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True, capture_output=True)
    commit(work, "a")
    git(work, "push", "-q", "origin", "HEAD:main")
    return remote, work


def test_each_merge_of_the_day_takes_the_next_number_and_the_tag_is_pushed(tmp_path: Path) -> None:
    remote, work = clone_pair(tmp_path)
    tag(work)
    commit(work, "b")
    tag(work)
    assert git(remote, "tag", "--list") == f"v{DAY}.1\nv{DAY}.2"


def test_a_rerun_on_the_same_merge_keeps_its_tag(tmp_path: Path) -> None:
    remote, work = clone_pair(tmp_path)
    tag(work)
    out = tag(work)
    assert "already" in out and git(remote, "tag", "--list") == f"v{DAY}.1", out


def test_a_merge_that_lost_the_race_takes_the_next_number(tmp_path: Path) -> None:
    remote, work = clone_pair(tmp_path)
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(remote), str(other)], check=True, capture_output=True)
    commit(other, "elsewhere")
    git(other, "push", "-q", "origin", "HEAD:side")
    # Another merge already pushed .1 while this clone has not fetched it.
    git(other, "tag", f"v{DAY}.1")
    git(other, "push", "-q", "origin", f"refs/tags/v{DAY}.1")
    out = tag(work)
    assert f"v{DAY}.2" in out and git(work, "tag", "--points-at", "HEAD") == f"v{DAY}.2", out


def test_a_dry_run_names_the_tag_and_makes_none(tmp_path: Path) -> None:
    _, work = clone_pair(tmp_path)
    out = tag(work, DRY="1")
    assert f"next is v{DAY}.1" in out and git(work, "tag", "--list") == "", out
