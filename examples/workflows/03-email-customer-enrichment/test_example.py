import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import apply_model_out_of_reach, ops_client, start_test_email

YAML = FOLDER / "resources" / "workflow.yaml"
WORKFLOW_ID = "email_customer_enrichment"


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


def test_known_customer_is_enriched() -> None:
    ops = ops_client()
    check = ops.workflows.validate(YAML)
    assert check.ok, check.errors
    event, expected = _case("known-customer")
    run = start_test_email(ops, WORKFLOW_ID, event)
    assert run["status"] == expected["status"]
    assert run["outcome"] == expected["outcome"]


def test_unknown_customer_is_not_found() -> None:
    ops = ops_client()
    event, expected = _case("unknown-customer")
    run = start_test_email(ops, WORKFLOW_ID, event)
    assert run["status"] == expected["status"]
    assert run["outcome"] == expected["outcome"]


def test_analysis_failure_is_named() -> None:
    ops = ops_client()
    event, _ = _case("known-customer")
    expected = json.loads((FOLDER / "expected" / "analysis-failed.json").read_text())
    workflow_id = apply_model_out_of_reach(ops, YAML)
    run = start_test_email(ops, workflow_id, event)
    assert run["status"] == expected["status"]
    assert run["outcome"] == expected["outcome"]
