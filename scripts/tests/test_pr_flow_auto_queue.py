"""auto-queue (scripts/pr_flow.py): what a push and a label do to a pull request's `reviewed` label and auto-merge."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pr_flow


class FakeGh:
    """Stands in for the gh command: records every call, fails the ones named in `fail`, answers the API reads."""

    def __init__(self, *, fail: tuple[str, ...] = (), permission: str = "write", armed: bool = True) -> None:
        self.calls: list[str] = []
        self.fail, self.permission, self.armed = fail, permission, armed

    def __call__(self, cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        line = " ".join(cmd[1:])
        self.calls.append(line)
        if any(f in line for f in self.fail):
            return subprocess.CompletedProcess(cmd, 1, "", "boom")
        if "/permission" in line:
            return subprocess.CompletedProcess(cmd, 0, self.permission + "\n", "")
        if "auto_merge != null" in line:
            return subprocess.CompletedProcess(cmd, 0, str(self.armed).lower() + "\n", "")
        if line.startswith("api repos/o/r/pulls/7"):
            info = {
                "base": {"ref": "develop", "repo": {"full_name": "o/r"}},
                "head": {"ref": "fix/x", "repo": {"full_name": "o/r"}},
                "labels": [{"name": "reviewed"}],
                "draft": False,
                "auto_merge": {"x": 1} if self.armed else None,
            }
            return subprocess.CompletedProcess(cmd, 0, json.dumps(info), "")
        return subprocess.CompletedProcess(cmd, 0, "", "")


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeGh:
    gh = FakeGh()
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setattr(subprocess, "run", gh)
    return gh


def test_any_push_takes_the_label_off_and_disarms_even_a_merge_of_develop(fake: FakeGh) -> None:
    assert pr_flow.cmd_auto_queue(7, "synchronize", False) == 0
    assert any("--remove-label reviewed" in c for c in fake.calls) and any("--disable-auto" in c for c in fake.calls)


def test_a_failed_label_removal_still_disarms_and_fails_the_job(fake: FakeGh) -> None:
    fake.fail = ("--remove-label",)
    assert pr_flow.cmd_auto_queue(7, "synchronize", False) == 1
    assert any("--disable-auto" in c for c in fake.calls)


def test_the_reviewed_label_of_someone_without_write_rights_comes_off_with_one_comment(fake: FakeGh) -> None:
    fake.permission = "triage"
    assert pr_flow.cmd_auto_queue(7, "labeled", False, label="reviewed", actor="someone") == 0
    assert (
        sum("--remove-label reviewed" in c for c in fake.calls) == 1 and sum(" comment " in c for c in fake.calls) == 1
    )
    assert not any("merge 7 --auto" in c for c in fake.calls)
