"""`make release-tag` (scripts/release-tag.sh) on scratch repositories, by failure mode: a release merge into develop is
tagged with the wrong version or not at all (the title is the commit's subject after a squash, the first body line of a
merge commit); an old-scheme merge from release/X.Y.Z is tagged; a rerun on the same merge changes the tag; a commit
that is no release merge gets a tag; a tag already naming another commit is moved instead of refused; a dry run makes
a tag."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "release-tag.sh"
RELEASE = "release: 1.2.0 into develop"
HOTFIX = "hotfix: 1.2.1 into develop"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


# The script reads GITHUB_ACTIONS and WALK_PASSED; CI sets the first, so a test builds its own environment.
CI_ONLY = ("GITHUB_ACTIONS", "WALK_PASSED")


def tag(repo: Path, **env: str) -> subprocess.CompletedProcess[str]:
    base = {k: v for k, v in os.environ.items() if k not in CI_ONLY}
    return subprocess.run(
        ["sh", str(SCRIPT)], cwd=repo, capture_output=True, text=True, env={**base, **env}, check=False
    )


def commit(repo: Path, name: str, message: str | None = None, body: str | None = None) -> str:
    (repo / name).write_text(name)
    git(repo, "add", name)
    extra = ["-m", body] if body else []
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--no-verify", "-m", message or name, *extra)
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
    commit(work, "c", "Merge pull request #8 from chanl-ai/feat/api-thing", body="feat(api): a thing")
    assert "gets no tag" in tag(work).stdout
    commit(work, "e", "Merge pull request #7 from chanl-ai/release/1.2.0")
    assert "gets no tag" in tag(work).stdout
    commit(work, "d", RELEASE)
    assert "next is v1.2.0" in tag(work, DRY="1").stdout
    assert git(remote, "tag", "--list") == "" and git(work, "tag", "--list") == ""


def test_a_queue_merge_commit_is_tagged_from_the_pull_request_title_in_its_body(tmp_path: Path) -> None:
    remote, work = clone_pair(tmp_path)
    queue = "Merge pull request #12 from chanl-ai/gh-readonly-queue/develop/pr-12-abc"
    merge = commit(work, "b", queue, body=RELEASE)
    squash = commit(work, "c", f"{HOTFIX} (#13)")
    assert tag(work, REF=merge).returncode == 0 and tag(work, REF=squash).returncode == 0
    assert git(remote, "rev-list", "-n", "1", "v1.2.0") == merge
    assert git(remote, "rev-list", "-n", "1", "v1.2.1") == squash


def test_auto_bump_tags_a_feature_as_the_next_minor_a_fix_as_the_next_patch_and_nothing_else(tmp_path: Path) -> None:
    remote, work = clone_pair(tmp_path)
    commit(work, "b", RELEASE)
    tag(work)
    git(work, "tag", "v2026-11-24.1")  # an old date tag never counts as the highest version
    feat = commit(work, "c", "feat(console): saved views (#40)")
    assert tag(work, BUMP="auto").returncode == 0
    fix = commit(work, "d", "fix(api): paging (#41)")
    assert tag(work, BUMP="auto").returncode == 0
    commit(work, "e", "chore(ci): tidy (#42)")
    assert "gets no tag" in tag(work, BUMP="auto").stdout
    assert git(remote, "rev-list", "-n", "1", "v1.3.0") == feat
    assert git(remote, "rev-list", "-n", "1", "v1.3.1") == fix


def test_auto_bump_reads_the_pull_request_title_from_a_merge_commit_body(tmp_path: Path) -> None:
    remote, work = clone_pair(tmp_path)
    commit(work, "b", RELEASE)
    tag(work)
    queue = "Merge pull request #50 from chanl-ai/gh-readonly-queue/develop/pr-50-abc"
    feat = commit(work, "c", queue, body="feat(console): saved views")
    assert tag(work, BUMP="auto").returncode == 0
    fix = commit(work, "d", queue, body="fix(api): paging (#51)")
    assert tag(work, BUMP="auto").returncode == 0
    commit(work, "e", queue, body="chore(ci): tidy")
    assert "gets no tag" in tag(work, BUMP="auto").stdout
    assert git(remote, "rev-list", "-n", "1", "v1.3.0") == feat
    assert git(remote, "rev-list", "-n", "1", "v1.3.1") == fix


def test_a_commit_that_already_has_a_version_tag_gets_no_second_one(tmp_path: Path) -> None:
    remote, work = clone_pair(tmp_path)
    commit(work, "b", RELEASE)
    tag(work)
    feat = commit(work, "c", "feat(console): saved views (#40)")
    assert tag(work, BUMP="auto").returncode == 0
    again = tag(work, BUMP="auto")
    assert again.returncode == 0 and "already v1.3.0" in again.stdout
    assert git(remote, "tag", "--points-at", feat) == "v1.3.0"


def test_a_tag_made_on_github_needs_a_recorded_walk_and_a_local_run_does_not(tmp_path: Path) -> None:
    remote, work = clone_pair(tmp_path)
    commit(work, "b", RELEASE)
    refused = tag(work, GITHUB_ACTIONS="true")
    assert refused.returncode == 1 and "no passed staging walk" in refused.stderr
    assert git(remote, "tag", "--list") == ""
    assert tag(work, GITHUB_ACTIONS="true", WALK_PASSED="1").returncode == 0
    assert git(remote, "tag", "--list") == "v1.2.0"
