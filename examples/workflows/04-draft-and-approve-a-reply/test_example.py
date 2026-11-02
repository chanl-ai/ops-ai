import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import apply_model_out_of_reach, inspect_run, ops_client, run_has_human_task, start_test_email, wait_ended

YAML = FOLDER / "resources" / "workflow.yaml"
WORKFLOW_ID = "draft_and_approve_reply"


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


def _run_id(run: dict) -> str:
    return str(run.get("id") or run.get("runId"))


def _apply() -> str:
    ops = ops_client()
    check = ops.workflows.validate(YAML)
    assert check.ok, check.errors
    made = ops.workflows.apply(YAML)
    try:
        ops.workflows.publish(made["workflowId"], note="W4 human review")
    except Exception:
        pass
    return str(made["workflowId"])


def _send_ran(run: dict) -> bool:
    return any(
        (step.get("nodeId") or step.get("id")) == "send" and str(step.get("status") or "") in {"succeeded", "ok"}
        for step in (run.get("steps") or [])
    )


def test_watch_and_inspect_stop_at_waiting_with_a_task() -> None:
    ops = ops_client()
    _apply()
    event, _ = _case("complaint")
    waiting = start_test_email(ops, WORKFLOW_ID, event)
    assert waiting["status"] == "waiting"
    assert waiting.get("taskId"), waiting
    inspected = inspect_run(ops, _run_id(waiting))
    assert inspected["status"] == "waiting"
    payload = (inspected.get("waiting") or {}).get("payload") or {}
    assert payload.get("review_id") or inspected.get("taskId")


def test_approved_reply_is_sent() -> None:
    ops = ops_client()
    _apply()
    check = ops.workflows.validate(YAML)
    assert check.ok, check.errors
    event, expected = _case("complaint")
    waiting = start_test_email(ops, WORKFLOW_ID, event)
    assert waiting["status"] == "waiting"
    assert waiting.get("taskId"), waiting
    assert run_has_human_task(waiting)
    ops.tasks.decide(waiting["taskId"], "approve")
    done = ops.runs.wait(_run_id(waiting))
    assert done["status"] == expected["status"]
    assert done["outcome"] == expected["outcome"]
    assert _send_ran(done), done.get("steps")


def test_rejected_reply_is_not_sent() -> None:
    ops = ops_client()
    _apply()
    event, expected = _case("reject")
    waiting = start_test_email(ops, WORKFLOW_ID, event)
    assert waiting["status"] == "waiting"
    assert waiting.get("taskId"), waiting
    ops.tasks.decide(waiting["taskId"], "reject")
    done = ops.runs.wait(_run_id(waiting))
    assert done["status"] == expected["status"]
    assert done["outcome"] == expected["outcome"]
    assert not _send_ran(done)


def test_review_timeout_escalates_with_no_send() -> None:
    ops = ops_client()
    _apply()
    event, expected = _case("timeout")
    waiting = start_test_email(ops, WORKFLOW_ID, event)
    assert waiting["status"] == "waiting"
    assert waiting.get("taskId"), waiting
    done = wait_ended(ops, _run_id(waiting), timeout=30)
    assert done["status"] == expected["status"], done
    assert done["outcome"] == expected["outcome"], done
    assert not _send_ran(done)


def test_model_failure_is_named() -> None:
    ops = ops_client()
    _apply()
    event, _ = _case("complaint")
    expected = json.loads((FOLDER / "expected" / "broken.json").read_text())
    workflow_id = apply_model_out_of_reach(ops, YAML)
    run = start_test_email(ops, workflow_id, event)
    assert run["status"] == expected["status"]
    assert run["outcome"] == expected["outcome"]
