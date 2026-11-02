import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import chat_agent, chat_reply, chat_tool_names, folder_bindings, ops_client


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def test_chat_starts_the_hold_workflow() -> None:
    expected = json.loads((FOLDER / "expected/started.json").read_text())
    message = json.loads((FOLDER / "fixtures/question.json").read_text())["message"]
    result = chat_agent(ops_client(), folder_bindings(FOLDER)["agentId"], message)
    names = chat_tool_names(result)
    reply = chat_reply(result)
    assert bool(reply) is expected["hasReply"]
    assert expected["called"] in names or any("calculate_account_hold" in n or n.startswith("workflow:") for n in names)
    text = json.dumps(result).lower()
    assert "wfrun_" in text or "runid" in text or "run_id" in text or any("hold" in n for n in names)
