"""How a Stuck run reads on a case and in a parent's list of the runs it started (c-561), by failure mode: a run the
reconciler marked Stuck reads "Running", so nobody looks at it."""

from __future__ import annotations

from ops_agents.api.run_story import state_of


def test_a_stuck_run_reads_stuck_not_running() -> None:
    assert state_of({"status": "stuck"}, None, "Their accounts", open_task=False) == "Stuck"
