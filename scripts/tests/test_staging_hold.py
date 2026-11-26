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
