"""A run lists the runs its steps started (c-209's for each), by failure mode: a child shown without its status, the
items out of order, and a child the tenant cannot see (another tenant's id in a step's output) listed anyway."""

from __future__ import annotations

from typing import Any

import pytest

from ops_agents.api.routers.engine import decisions_in, files_in, started_runs


class _Runs:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.asked: list[list[str]] = []

    async def many(self, run_ids: list[str]) -> list[dict[str, Any]]:
        self.asked.append(run_ids)
        return [r for r in self.rows if r["id"] in run_ids]


STEPS: list[dict[str, Any]] = [
    {"nodeId": "read", "output": {"records": [1, 2]}},
    {
        "nodeId": "each",
        "output": {
            "workflowId": "levy_case",
            "count": 3,
            "runs": [
                {"index": 0, "runId": "wfrun_a"},
                {"index": 1, "runId": "wfrun_b"},
                {"index": 2, "runId": "wfrun_x"},
            ],
        },
    },
]


@pytest.mark.asyncio
async def test_each_started_run_is_listed_in_item_order_with_its_status_in_one_read() -> None:
    store = _Runs(
        [
            {"id": "wfrun_b", "status": "waiting", "outcome": None},
            {"id": "wfrun_a", "status": "succeeded", "outcome": "saved"},
        ]
    )
    got = await started_runs(store, STEPS)  # type: ignore[arg-type]
    assert got == [
        {"nodeId": "each", "index": 0, "runId": "wfrun_a", "status": "succeeded", "outcome": "saved"},
        {"nodeId": "each", "index": 1, "runId": "wfrun_b", "status": "waiting", "outcome": None},
    ]
    # One query for every child; wfrun_x is no run of this tenant, so it is left out.
    assert store.asked == [["wfrun_a", "wfrun_b", "wfrun_x"]]


def test_files_in_finds_each_file_id_once_at_any_depth_and_nothing_else() -> None:
    a, b = "fil_" + "a" * 32, "fil_" + "b" * 32
    given = {
        "documentFileId": a,
        "files": [{"fileId": b, "name": "TEST012.pdf"}],
        "again": [a],
        "note": f"see {a}",
        "short": "fil_abc",
    }
    # A file id inside free text is not a file the run was given; only whole values are. An upload's name comes along.
    assert files_in(given) == [{"id": a, "name": None}, {"id": b, "name": "TEST012.pdf"}]
    assert files_in(None) == []


def test_decisions_in_lists_each_decided_task_with_who_when_why_and_its_task() -> None:
    steps: list[dict[str, Any]] = [
        {"nodeId": "read", "iteration": 0, "status": "ok", "output": {"fileId": "f"}, "attempts": []},
        {
            "nodeId": "person",
            "iteration": 0,
            "status": "ok",
            "output": {"decision": "approve", "reason": "Matches the notice", "by": "p.shah@northfieldbank.com"},
            "attempts": [{"finishedAt": "2026-10-19T12:00:00+00:00"}],
        },
        # Still waiting: no decision yet, so nothing is listed for it.
        {"nodeId": "second", "iteration": 0, "status": "waiting", "output": None, "attempts": []},
    ]
    assert decisions_in("wfrun_1", steps) == [
        {
            "nodeId": "person",
            "iteration": 0,
            "reviewId": "wfrun_1:person:0",
            "action": "approve",
            "reason": "Matches the notice",
            "by": "p.shah@northfieldbank.com",
            "at": "2026-10-19T12:00:00+00:00",
        }
    ]
