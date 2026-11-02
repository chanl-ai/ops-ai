import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import ops_client, start_file_deleted, upload_bytes

YAML = FOLDER / "resources" / "workflow.yaml"
SYSTEM = "file_deleted_purge"


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def _expected(name: str) -> dict:
    return json.loads((FOLDER / "expected" / f"{name}.json").read_text())


def _apply() -> str:
    ops = ops_client()
    check = ops.workflows.validate(YAML)
    assert check.ok, check.errors
    made = ops.workflows.apply(YAML)
    return str(made["workflowId"])


def test_deleted_file_is_purged() -> None:
    ops = ops_client()
    _apply()
    expected = _expected("deleted")
    _, run = start_file_deleted(ops)
    assert run["status"] == expected["status"], run
    assert run["outcome"] == expected["outcome"], run


def test_duplicate_event_is_purged_again() -> None:
    ops = ops_client()
    expected = _expected("again")
    file_id, first = start_file_deleted(ops, name="purge-again.txt")
    assert first["status"] == expected["status"], first
    assert first["outcome"] == expected["outcome"], first
    run = ops.workflows.run(SYSTEM, input={"fileId": file_id}, mode="test", wait=True)
    assert run["status"] == expected["status"], run
    assert run["outcome"] == expected["outcome"], run


def test_a_file_that_still_exists_fails() -> None:
    ops = ops_client()
    workflow_id = _apply()
    expected = _expected("wrong")
    file_id = upload_bytes(ops, "still-here.txt", b"do-not-delete\n")
    run = ops.workflows.run(workflow_id, input={"fileId": file_id}, mode="test", wait=True)
    assert run["status"] == expected["status"], run
    assert run["outcome"] == expected["outcome"], run
