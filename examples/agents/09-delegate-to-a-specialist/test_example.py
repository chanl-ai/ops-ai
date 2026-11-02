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


def test_triage_calls_the_specialist_as_a_tool() -> None:
    ops = ops_client()
    bindings = folder_bindings(FOLDER)
    message = json.loads((FOLDER / "fixtures/question.json").read_text())["message"]
    result = chat_agent(ops, bindings["agentId"], message)
    names = chat_tool_names(result)
    blob = json.dumps(result)
    specialist = str(bindings.get("specialistId") or "")
    assert bool(chat_reply(result))
    assert (
        any(name.startswith("agent__") or specialist in name for name in names)
        or f"agent__{specialist}" in blob
        or specialist in blob
    )
