import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import email_with_file, ops_client, run_has_human_task, upload_bytes, wait_run

YAML = FOLDER / "resources" / "workflow.yaml"
WORKFLOW_ID = "read_claim_and_open_case"


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def _case(name: str) -> tuple[dict, dict]:
    event = json.loads((FOLDER / "fixtures" / f"{name}.json").read_text())
    expected = json.loads((FOLDER / "expected" / f"{name}.json").read_text())
    return event, expected


def _event_with_file(ops, name: str) -> tuple[dict, dict]:
    event, expected = _case(name)
    path = FOLDER / "fixtures" / str(event.pop("file"))
    file_id = upload_bytes(ops, path.name, path.read_bytes(), mime="text/plain")
    return email_with_file(event, file_id), expected


def _run_id(run: dict) -> str:
    return str(run.get("id") or run.get("runId"))


def test_clean_claim_opens_a_typed_case() -> None:
    ops = ops_client()
    check = ops.workflows.validate(YAML)
    assert check.ok, check.errors
    event, expected = _event_with_file(ops, "claim")
    started = ops.workflows.send_test_email(WORKFLOW_ID, event, mode="test")
    run = wait_run(ops, started["runId"])
    assert run["status"] == expected["status"], run
    assert run["outcome"] == expected["outcome"], run


def test_low_confidence_waits_then_opens_a_case() -> None:
    ops = ops_client()
    event, expected = _event_with_file(ops, "low")
    started = ops.workflows.send_test_email(WORKFLOW_ID, event, mode="test")
    waiting = wait_run(ops, started["runId"])
    assert waiting["status"] == "waiting", waiting
    assert run_has_human_task(waiting), waiting
    task_id = waiting.get("taskId") or (waiting.get("waiting") or {}).get("payload", {}).get("review_id")
    assert task_id, waiting
    ops.tasks.decide(task_id, "approve")
    done = wait_run(ops, _run_id(waiting))
    assert done["status"] == expected["status"], done
    assert done["outcome"] == expected["outcome"], done


def test_unreadable_claim_ends_named() -> None:
    ops = ops_client()
    event, expected = _event_with_file(ops, "unreadable")
    started = ops.workflows.send_test_email(WORKFLOW_ID, event, mode="test")
    run = wait_run(ops, started["runId"])
    assert run["status"] == expected["status"], run
    assert run["outcome"] == expected["outcome"], run
