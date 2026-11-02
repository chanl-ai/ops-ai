import json
import sys
from pathlib import Path

import pytest
from ops_ai.errors import OpsError

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


def test_validate_apply_and_test_run_accepts_a_valid_request() -> None:
    ops = ops_client()
    check = ops.workflows.validate(YAML)
    assert check.ok, check.errors
    made = ops.workflows.apply(YAML)
    payload = json.loads((FOLDER / "fixtures/valid.json").read_text())
    expected = json.loads((FOLDER / "expected/accepted.json").read_text())
    run = ops.workflows.run(made["workflowId"], input=payload, mode="test", wait=True)
    assert run["status"] == expected["status"]
    assert run["outcome"] == expected["outcome"]


def test_missing_email_fails_with_schema_path() -> None:
    ops = ops_client()
    ops.workflows.apply(YAML)
    payload = json.loads((FOLDER / "fixtures/missing-email.json").read_text())
    try:
        ops.workflows.run("normalize_support_request", input=payload, mode="test", wait=True)
    except OpsError as exc:
        details = exc.details if isinstance(exc.details, dict) else {}
        assert exc.status == 422
        assert exc.code == "invalid_input"
        assert details.get("path") == "customerEmail"
        return
    raise AssertionError("missing customerEmail was accepted")
