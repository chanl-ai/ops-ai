import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import ops_client, resume_wait, wait_run

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


def test_callback_success_clears() -> None:
    ops = ops_client()
    workflow_id = _apply()
    payload, expected = _case("clear")
    run = ops.workflows.run(workflow_id, input=payload, mode="test", wait=True)
    assert run["status"] == "waiting", run
    assert not run.get("taskId"), run
    resume_wait(ops, run, {"status": "clear"})
    done = wait_run(ops, _run_id(run), timeout=30)
    assert done["status"] == expected["status"], done
    assert done["outcome"] == expected["outcome"], done


def test_ambiguous_result_is_reviewed_then_flagged() -> None:
    ops = ops_client()
    workflow_id = _apply()
    payload, expected = _case("review")
    run = ops.workflows.run(workflow_id, input=payload, mode="test", wait=True)
    assert run["status"] == "waiting", run
    resume_wait(ops, run, {"status": "review"})
    waiting = wait_run(ops, _run_id(run), timeout=30)
    assert waiting.get("taskId"), waiting
    ops.tasks.decide(waiting["taskId"], "reject")
    done = ops.runs.wait(_run_id(waiting))
    assert done["status"] == expected["status"], done
    assert done["outcome"] == expected["outcome"], done


def test_start_failure_is_check_failed() -> None:
    ops = ops_client()
    workflow_id = _apply()
    payload, expected = _case("missing")
    run = ops.workflows.run(workflow_id, input=payload, mode="test", wait=True)
    assert run["status"] == expected["status"], run
    assert run["outcome"] == expected["outcome"], run


def test_timeout_is_check_failed() -> None:
    ops = ops_client()
    workflow_id = _apply()
    payload, expected = _case("timeout")
    run = ops.workflows.run(workflow_id, input=payload, mode="test", wait=True)
    assert run["status"] == "waiting", run
    done = wait_run(ops, _run_id(run), timeout=30)
    assert done["status"] == expected["status"], done
    assert done["outcome"] == expected["outcome"], done
