import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import chat_agent, chat_reply, folder_bindings, ops_client


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def test_published_agent_answers_through_chat() -> None:
    message = json.loads((FOLDER / "fixtures/question.json").read_text())["message"]
    expected = json.loads((FOLDER / "expected/reply.json").read_text())
    result = chat_agent(ops_client(), folder_bindings(FOLDER)["agentId"], message)
    assert bool(chat_reply(result)) is expected["hasReply"]
    assert result.get("threadId")
