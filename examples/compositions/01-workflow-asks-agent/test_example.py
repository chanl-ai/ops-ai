import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import folder_bindings, ops_client, run_answer_text, run_has_human_task

YAML = FOLDER / "resources" / "workflow.yaml"


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def test_workflow_asks_agent_returns_the_cited_answer() -> None:
    ops = ops_client()
    check = ops.workflows.validate(YAML)
    assert check.ok, check.errors
    bindings = folder_bindings(FOLDER)
    payload = json.loads((FOLDER / "fixtures/ask.json").read_text())
    expected = json.loads((FOLDER / "expected/answered.json").read_text())
    run = ops.workflows.run(bindings["workflowId"], input=payload, mode="test", wait=True)
    text = run_answer_text(run).lower()
    blob = text + json.dumps(run.get("output") or {}).lower()
    assert run["status"] == expected["status"]
    assert run["outcome"] == expected["outcome"]
    assert run_has_human_task(run) is expected["hasHumanTask"]
    assert bool(text) is expected["hasCitedAnswer"]
    assert any(word in blob for word in ("account opening", "document", "sole proprietor", "beneficial"))
    assert "[" in blob or "citation" in blob
