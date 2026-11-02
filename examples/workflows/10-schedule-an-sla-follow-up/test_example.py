import json
import sys
import time
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import ops_client, wait_run

YAML = FOLDER / "resources" / "workflow.yaml"


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def _case(name: str) -> tuple[dict, dict]:
    return (
        json.loads((FOLDER / "fixtures" / f"{name}.json").read_text()),
        json.loads((FOLDER / "expected" / f"{name}.json").read_text()),
    )


def _apply() -> str:
    ops = ops_client()
    check = ops.workflows.validate(YAML)
    assert check.ok, check.errors
    made = ops.workflows.apply(YAML)
    return str(made["workflowId"])


def _run_id(run: dict) -> str:
    return str(run.get("id") or run.get("runId"))


def _soon(seconds: int = 3) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + seconds))


def test_future_date_waits_then_the_review_closes() -> None:
    ops = ops_client()
    workflow_id = _apply()
    _, expected = _case("future")
    run = ops.workflows.run(workflow_id, input={"dueOn": _soon(3)}, mode="test", wait=True)
    assert run["status"] == "waiting", run
    assert not run.get("taskId"), run
    waiting = wait_run(ops, _run_id(run), timeout=30)
    assert waiting.get("taskId"), waiting
    ops.tasks.decide(waiting["taskId"], "approve")
    done = ops.runs.wait(_run_id(waiting))
    assert done["status"] == expected["status"], done
    assert done["outcome"] == expected["outcome"], done


def test_past_date_continues_immediately() -> None:
    ops = ops_client()
    workflow_id = _apply()
    payload, expected = _case("past")
    began = time.monotonic()
    run = ops.workflows.run(workflow_id, input=payload, mode="test", wait=True)
    assert time.monotonic() - began < 2.0, run
    assert run["status"] == expected["status"], run
    assert run.get("taskId"), run


def test_invalid_date_takes_error() -> None:
    ops = ops_client()
    workflow_id = _apply()
    payload, expected = _case("invalid")
    run = ops.workflows.run(workflow_id, input=payload, mode="test", wait=True)
    assert run["status"] == expected["status"], run
    assert run["outcome"] == expected["outcome"], run
