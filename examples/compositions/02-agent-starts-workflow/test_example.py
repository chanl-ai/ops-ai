import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import (
    chat_agent,
    chat_child_run_id,
    chat_reply,
    chat_tool_names,
    folder_bindings,
    ops_client,
    run_has_human_task,
)


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def test_agent_starts_workflow_returns_the_three_node_output() -> None:
    ops = ops_client()
    bindings = folder_bindings(FOLDER)
    message = json.loads((FOLDER / "fixtures/message.json").read_text())["message"]
    expected = json.loads((FOLDER / "expected/started.json").read_text())
    result = chat_agent(ops, bindings["agentId"], message)
    names = chat_tool_names(result)
    blob = json.dumps(result)
    child_id = chat_child_run_id(result)
    assert bool(chat_reply(result)) is expected["hasOutput"]
    assert any("normalize_support_request" in name for name in names) or "workflow__normalize_support_request" in blob
    assert child_id, blob
    run = ops.runs.wait(child_id)
    assert run["status"] == "succeeded"
    assert run["outcome"] == expected["outcome"]
    assert run_has_human_task(run) is expected["hasHumanTask"]
    assert "waiting_review" not in blob
