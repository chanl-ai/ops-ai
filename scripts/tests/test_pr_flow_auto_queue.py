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

    def __init__(
        self, *, fail: tuple[str, ...] = (), permission: str = "write", armed: bool = True, head: str = "fix/x"
    ) -> None:
        self.calls: list[str] = []
        self.fail, self.permission, self.armed, self.head = fail, permission, armed, head

    def __call__(self, cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        line = " ".join(cmd[1:])
        self.calls.append(line)
        if any(f in line for f in self.fail):
            return subprocess.CompletedProcess(cmd, 1, "", "boom")
        if line.endswith(".head.ref"):
            return subprocess.CompletedProcess(cmd, 0, self.head + "\n", "")
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


def test_any_push_takes_the_label_off_and_disarms_and_a_failed_removal_still_disarms_and_fails(fake: FakeGh) -> None:
    assert pr_flow.cmd_auto_queue(7, "synchronize", False) == 0
    assert any("--remove-label reviewed" in c for c in fake.calls) and any("--disable-auto" in c for c in fake.calls)
    fake.calls.clear()
    fake.fail = ("--remove-label",)
    assert pr_flow.cmd_auto_queue(7, "synchronize", False) == 1
    assert any("--disable-auto" in c for c in fake.calls)


def test_the_push_that_arms_a_merge_back_does_not_disarm_it(fake: FakeGh) -> None:
    fake.head = "merge-back/release-1.2.1"
    assert pr_flow.cmd_auto_queue(7, "synchronize", False) == 0
    assert not any("--disable-auto" in c or "--remove-label" in c for c in fake.calls)


def test_the_reviewed_label_of_someone_without_write_rights_comes_off_with_one_comment(fake: FakeGh) -> None:
    fake.permission = "triage"
    assert pr_flow.cmd_auto_queue(7, "labeled", False, label="reviewed", actor="someone") == 0
    assert (
        sum("--remove-label reviewed" in c for c in fake.calls) == 1 and sum(" comment " in c for c in fake.calls) == 1
    )
    assert not any("merge 7 --auto" in c for c in fake.calls)


def _pr(**kw: Any) -> dict[str, Any]:
    return {"labels": ["reviewed"], "head": "fix/x", "author": "dev", "fork": False, **kw}


def _mark(event: str, at: str, actor: str = "maint") -> dict[str, str]:
    return {"event": event, "label": "reviewed", "actor": actor, "at": at}


@pytest.mark.parametrize(
    ("pr", "events", "access", "passes"),
    [
        (_pr(), [_mark("labeled", "2026-11-28T10:00:00Z")], "write", True),
        (_pr(), [_mark("labeled", "2026-11-28T08:00:00Z")], "write", False),  # before the last push
        (_pr(), [_mark("labeled", "2026-11-28T10:00:00Z")], "triage", False),  # by someone without write
        (_pr(), [_mark("labeled", "2026-11-28T10:00:00Z"), _mark("unlabeled", "2026-11-28T11:00:00Z")], "write", False),
        (_pr(labels=["reviewed", "hold"]), [_mark("labeled", "2026-11-28T10:00:00Z")], "write", False),
        (_pr(head="merge-back/release-1.2.1", author="github-actions[bot]", labels=[]), [], "", True),
        (_pr(head="merge-back/release-1.2.1", labels=[]), [], "", False),  # a person's merge-back needs the label
    ],
)
def test_the_queue_takes_only_a_pull_request_reviewed_by_a_maintainer_after_its_last_push(
    pr: dict[str, Any], events: list[dict[str, str]], access: str, passes: bool
) -> None:
    assert (pr_flow.review_problems(pr, events, "2026-11-28T09:00:00Z", lambda _a: access) == []) is passes


def test_the_queue_run_fails_closed_when_the_review_cannot_be_read(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_a: Any, **_k: Any) -> str:
        raise SystemExit("gh api: 502")

    monkeypatch.setenv("GROUP_REF", "refs/heads/gh-readonly-queue/develop/pr-7-abc123")
    monkeypatch.setattr(pr_flow, "gh", broken)
    reasons = pr_flow.queue_review_reasons()
    assert reasons and "fails closed" in reasons[0], reasons
