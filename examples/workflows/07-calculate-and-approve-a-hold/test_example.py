import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import approve_write, ops_client

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


def test_approved_hold_is_placed() -> None:
    ops = ops_client()
    workflow_id = _apply()
    payload, expected = _case("hold")
    run = ops.workflows.run(workflow_id, input=payload, mode="test", wait=True)
    assert run["status"] == "waiting", run
    assert run.get("taskId"), run
    approve_write(ops, run["taskId"])
    done = ops.runs.wait(_run_id(run))
    assert done["status"] == expected["status"], done
    assert done["outcome"] == expected["outcome"], done


def test_unknown_customer_is_not_found() -> None:
    ops = ops_client()
    workflow_id = _apply()
    payload, expected = _case("missing")
    run = ops.workflows.run(workflow_id, input=payload, mode="test", wait=True)
    assert run["status"] == expected["status"], run
    assert run["outcome"] == expected["outcome"], run


def test_no_account_is_a_named_hold_failure() -> None:
    ops = ops_client()
    workflow_id = _apply()
    payload, expected = _case("failed")
    run = ops.workflows.run(workflow_id, input=payload, mode="test", wait=True)
    if run["status"] == "waiting" and run.get("taskId"):
        approve_write(ops, run["taskId"])
        run = ops.runs.wait(_run_id(run))
    assert run["status"] == expected["status"], run
    assert run["outcome"] == expected["outcome"], run
