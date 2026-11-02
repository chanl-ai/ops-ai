import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import _ensure_ai_steps, _needs_ai_steps, apply_model_out_of_reach, ops_client
from ops_ai._io import load_data

YAML = FOLDER / "resources" / "workflow.yaml"


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def _apply() -> str:
    ops = ops_client()
    definition = load_data(YAML)
    if _needs_ai_steps(definition):
        _ensure_ai_steps(ops)
    check = ops.workflows.validate(YAML)
    assert check.ok, check.errors
    made = ops.workflows.apply(YAML)
    return str(made["workflowId"])


def _run(name: str) -> dict:
    ops = ops_client()
    workflow_id = _apply()
    payload = json.loads((FOLDER / "fixtures" / f"{name}.json").read_text())
    expected = json.loads((FOLDER / "expected" / f"{name}.json").read_text())
    run = ops.workflows.run(workflow_id, input=payload, mode="test", wait=True)
    assert run["status"] == expected["status"], run
    assert run["outcome"] == expected["outcome"], run
    return run


def test_billing_message_ends_on_the_billing_queue() -> None:
    _run("billing")


def test_low_confidence_takes_the_otherwise_end() -> None:
    _run("unsure")


def test_model_failure_ends_as_classify_failed() -> None:
    ops = ops_client()
    _apply()
    expected = json.loads((FOLDER / "expected" / "broken.json").read_text())
    payload = json.loads((FOLDER / "fixtures" / "billing.json").read_text())
    workflow_id = apply_model_out_of_reach(ops, YAML)
    run = ops.workflows.run(workflow_id, input=payload, mode="test", wait=True)
    assert run["status"] == expected["status"], run
    assert run["outcome"] == expected["outcome"], run
