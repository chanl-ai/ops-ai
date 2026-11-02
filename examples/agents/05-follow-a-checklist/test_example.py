import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import agent_skill_pins, chat_agent, chat_reply, folder_bindings, ops_client


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


def test_blocked_topic_is_refused() -> None:
    expected = json.loads((FOLDER / "expected/blocked.json").read_text())
    result = _chat("blocked.json")
    reply = chat_reply(result).lower()
    assert bool(chat_reply(result)) is expected["hasReply"]
    assert expected["refused"] is True
    assert "investment" in reply
    assert "can't" in reply or "cannot" in reply or "licensed" in reply


def test_allowed_checklist_topic_proceeds() -> None:
    expected = json.loads((FOLDER / "expected/checklist.json").read_text())
    ops = ops_client()
    pins = agent_skill_pins(ops, folder_bindings(FOLDER)["agentId"])
    names = {str(pin.get("name") or "") for pin in pins}
    result = _chat("question.json")
    reply = chat_reply(result)
    assert bool(reply) is expected["hasReply"]
    assert expected["skill"] in names
    pinned = next(pin for pin in pins if pin.get("name") == expected["skill"])
    assert int(pinned.get("pinnedVersion") or 0) >= 1
    assert "should my client buy" not in reply.lower()
