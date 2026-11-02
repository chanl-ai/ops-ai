import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import READ_TOOL, chat_agent, chat_reply, chat_tool_names, folder_bindings, ops_client


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def _chat(name: str) -> dict:
    message = json.loads((FOLDER / "fixtures" / name).read_text())["message"]
    return chat_agent(ops_client(), folder_bindings(FOLDER)["agentId"], message)


def test_agent_calls_the_r1_read_tool() -> None:
    expected = json.loads((FOLDER / "expected/tool.json").read_text())
    result = _chat("question.json")
    names = chat_tool_names(result)
    reply = chat_reply(result)
    assert bool(reply) is expected["hasReply"]
    assert expected["called"] in names
    assert READ_TOOL in names
    assert "ada@example.test" in reply.lower() or "ada" in reply.lower()


def test_missing_customer_takes_the_documented_failure() -> None:
    expected = json.loads((FOLDER / "expected/missing.json").read_text())
    result = _chat("missing.json")
    names = chat_tool_names(result)
    reply = chat_reply(result).lower()
    assert bool(chat_reply(result)) is expected["hasReply"]
    assert expected["called"] in names
    assert expected["notFound"] is True
    assert "no customer" in reply or "not found" in reply or "does not match" in reply or "nobody" in reply


def test_write_request_is_refused() -> None:
    expected = json.loads((FOLDER / "expected/refused.json").read_text())
    result = _chat("write.json")
    names = chat_tool_names(result)
    reply = chat_reply(result).lower()
    assert bool(chat_reply(result)) is expected["hasReply"]
    assert expected["refusedWrite"] is True
    assert "add_customer_note" not in names
    assert "do not write" in reply or "only look up" in reply
