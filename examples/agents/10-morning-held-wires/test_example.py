import json
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import folder_bindings, ops_client


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def test_a_due_tick_starts_one_job_run() -> None:
    ops = ops_client()
    agent_id = folder_bindings(FOLDER)["agentId"]
    job = json.loads((FOLDER / "fixtures/job.json").read_text())
    due = (datetime.now(UTC) - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    first = ops.agents.schedule(agent_id, job["message"], due_at=due, key=job["key"])
    second = ops.agents.schedule(agent_id, job["message"], due_at=due, key=job["key"])
    assert first.get("threadId")
    assert second.get("duplicate") or first.get("threadId") == second.get("threadId")
    deadline = time.monotonic() + 25
    runs: list = []
    while time.monotonic() < deadline:
        runs = list(ops.agents.trace(agent_id, limit=10) or [])
        if runs:
            break
        time.sleep(0.5)
    assert runs, "the due tick started no run"
