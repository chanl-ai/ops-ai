import json
import sys
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

from datetime import UTC, datetime, timedelta


def test_a_due_tick_starts_one_run() -> None:
    ops = ops_client()
    workflow_id = folder_bindings(FOLDER)["workflowId"]
    due = (datetime.now(UTC) - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
    payload = json.loads((FOLDER / "fixtures/tick.json").read_text())
    first = ops.workflows.schedule(workflow_id, input=payload, due_at=due, key="morning")
    second = ops.workflows.schedule(workflow_id, input=payload, due_at=due, key="morning")
    assert first.get("runId")
    assert second.get("created") is False or second.get("runId") == first.get("runId")
    run = ops.runs.wait(first["runId"])
    assert run["outcome"] == json.loads((FOLDER / "expected/once.json").read_text())["outcome"]
