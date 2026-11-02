import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import ops_client

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


def test_matching_invoice_and_po_auto_complete() -> None:
    ops = ops_client()
    workflow_id = _apply()
    payload, expected = _case("match")
    run = ops.workflows.run(workflow_id, input=payload, mode="test", wait=True)
    assert run["status"] == expected["status"], run
    assert run["outcome"] == expected["outcome"], run


def test_mismatch_waits_then_records_the_resolution() -> None:
    ops = ops_client()
    workflow_id = _apply()
    payload, expected = _case("mismatch")
    opened = ops.cases.create({"subject": "AP reconcile example"})
    payload = {**payload, "caseId": opened["id"]}
    run = ops.workflows.run(workflow_id, input=payload, mode="test", wait=True)
    assert run["status"] == "waiting", run
    assert run.get("taskId"), run
    ops.tasks.decide(run["taskId"], "approve")
    done = ops.runs.wait(run.get("runId") or run["id"])
    assert done["status"] == expected["status"], done
    assert done["outcome"] == expected["outcome"], done


def test_missing_invoice_is_a_named_lookup_failure() -> None:
    ops = ops_client()
    workflow_id = _apply()
    payload, expected = _case("missing")
    run = ops.workflows.run(workflow_id, input=payload, mode="test", wait=True)
    assert run["status"] == expected["status"], run
    assert run["outcome"] == expected["outcome"], run
