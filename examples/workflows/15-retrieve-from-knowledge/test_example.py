import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import folder_bindings, ops_client


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def test_handbook_question_is_found_and_an_empty_query_is_not() -> None:
    ops = ops_client()
    workflow_id = folder_bindings(FOLDER)["workflowId"]
    found = ops.workflows.run(
        workflow_id, input=json.loads((FOLDER / "fixtures/question.json").read_text()), mode="test", wait=True
    )
    assert found["outcome"] == json.loads((FOLDER / "expected/found.json").read_text())["outcome"]
    missing = ops.workflows.run(
        workflow_id, input=json.loads((FOLDER / "fixtures/empty.json").read_text()), mode="test", wait=True
    )
    assert missing["outcome"] == json.loads((FOLDER / "expected/missing.json").read_text())["outcome"]
