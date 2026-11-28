"""scripts/staging_hold.py, the check deploy-staging.yml runs on the STAGING_HOLD variable, by failure mode: a hold
with no release prefix is accepted, a hold for a release that is already tagged still freezes staging, a live hold is
not reported as one."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "staging_hold.py"


def repo(tmp: Path, *tags: str) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "a",
        ],
        check=True,
    )
    for t in tags:
        subprocess.run(["git", "-C", str(tmp), "tag", t], check=True)
    return tmp


def check(cwd: Path, hold: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPT)], cwd=cwd, env={**os.environ, "HOLD": hold}, capture_output=True, text=True, check=False
    )


def test_no_hold_is_none(tmp_path: Path) -> None:
    r = check(repo(tmp_path), "")
    assert r.returncode == 0 and "state=none" in r.stdout and "\npin=\n" in r.stdout


def test_a_hold_for_an_untagged_release_is_active_and_keeps_its_text(tmp_path: Path) -> None:
    r = check(repo(tmp_path, "v1.0.0"), "1.1.0: under test on staging")
    assert r.returncode == 0 and "state=active" in r.stdout and "text=1.1.0: under test on staging" in r.stdout
    assert "\npin=STAGING_HOLD is set: 1.1.0: under test on staging\n" in r.stdout


def test_a_hold_for_a_release_that_is_tagged_is_stale_and_ignored(tmp_path: Path) -> None:
    r = check(repo(tmp_path, "v1.1.0"), "1.1.0: under test on staging")
    assert r.returncode == 0 and "state=ignored" in r.stdout and "v1.1.0" in r.stdout
    assert "\npin=\n" in r.stdout


def test_a_hold_without_a_release_prefix_is_refused(tmp_path: Path) -> None:
    for bad in ("under test", "1.1: under test", "1.1.0 under test", "v1.1.0: x"):
        r = check(repo(tmp_path / bad.replace(" ", "_").replace(":", "_"), "v1.1.0"), bad)
        assert r.returncode == 1 and "state=invalid" in r.stdout, bad


def test_a_branch_freeze_without_a_hold_is_a_pin_too(tmp_path: Path) -> None:
    r = subprocess.run(
        ["python3", str(SCRIPT)],
        cwd=repo(tmp_path),
        env={**os.environ, "HOLD": "", "BRANCHES": "release/1.2.0 hotfix/x"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0 and "pin=staging is frozen for release/1.2.0 hotfix/x" in r.stdout


def test_the_pin_joins_a_branch_freeze_and_a_live_hold(tmp_path: Path) -> None:
    r = subprocess.run(
        ["python3", str(SCRIPT)],
        cwd=repo(tmp_path),
        env={**os.environ, "HOLD": "1.1.0: under test", "BRANCHES": "release/1.1.0"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert "pin=staging is frozen for release/1.1.0; STAGING_HOLD is set: 1.1.0: under test" in r.stdout


def branch_at(repo_dir: Path, name: str, merged_into_head: bool) -> None:
    """A remote-tracking release branch: at HEAD's parent (merged) or on a commit HEAD lacks (unmerged)."""
    git = ["git", "-C", str(repo_dir), "-c", "user.name=t", "-c", "user.email=t@t"]
    if merged_into_head:
        sha = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        subprocess.run([*git, "update-ref", f"refs/remotes/origin/{name}", sha], check=True)
        subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "next"], check=True)
    else:
        subprocess.run([*git, "checkout", "-q", "-b", "side"], check=True)
        subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "side"], check=True)
        sha = subprocess.run([*git, "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        subprocess.run([*git, "update-ref", f"refs/remotes/origin/{name}", sha], check=True)
        subprocess.run([*git, "checkout", "-q", "-"], check=True)


def freeze(cwd: Path, branches: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["python3", str(SCRIPT)],
        cwd=cwd,
        env={**os.environ, "HOLD": "", "BRANCHES": branches, "SHA": "HEAD"},
        capture_output=True,
        text=True,
        check=False,
    )


def test_a_branch_already_merged_into_the_deployed_commit_does_not_freeze(tmp_path: Path) -> None:
    r = repo(tmp_path)
    branch_at(r, "release/1.1.0", True)
    out = freeze(r, "release/1.1.0").stdout
    assert "notice=release/1.1.0 is merged into develop, freeze ignored" in out and "\npin=\n" in out


def test_a_branch_with_commits_the_deployed_commit_lacks_still_freezes(tmp_path: Path) -> None:
    r = repo(tmp_path)
    branch_at(r, "release/1.1.0", True)
    branch_at(r, "hotfix/x", False)
    out = freeze(r, "release/1.1.0 hotfix/x").stdout
    assert "pin=staging is frozen for hotfix/x\n" in out and "notice=release/1.1.0" in out


def test_a_head_that_cannot_be_read_keeps_the_freeze(tmp_path: Path) -> None:
    out = freeze(repo(tmp_path), "release/9.9.9").stdout
    assert "pin=staging is frozen for release/9.9.9\n" in out and "notice=" not in out


def test_a_branch_merged_into_main_does_not_freeze_before_the_merge_back(tmp_path: Path) -> None:
    # A release goes into main first; develop holds its commits only after the merge-back pull request lands. Staging
    # returns to develop when main holds the branch, so the merge-back itself is not what unfreezes it.
    r = repo(tmp_path)
    branch_at(r, "release/1.3.0", False)
    git = ["git", "-C", str(r)]
    head = subprocess.run(
        [*git, "rev-parse", "refs/remotes/origin/release/1.3.0"], capture_output=True, text=True, check=True
    )
    subprocess.run([*git, "update-ref", "refs/remotes/origin/main", head.stdout.strip()], check=True)
    out = freeze(r, "release/1.3.0").stdout
    assert "notice=release/1.3.0 is merged into main, freeze ignored" in out and "\npin=\n" in out
