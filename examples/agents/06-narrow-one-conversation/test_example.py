import json
import sys
from pathlib import Path

import pytest
from ops_ai.errors import BadRequest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import (
    READ_TOOL,
    chat_reply,
    chat_tool_names,
    folder_bindings,
    ops_client,
    patch_thread_settings,
    send_chat,
    start_chat_thread,
    thread_settings,
)


def _stack() -> bool:
    try:
        ops_client()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _stack(), reason="run this folder's setup.py on a stack first")


def _bindings() -> dict:
    return folder_bindings(FOLDER)


def test_widen_override_is_refused() -> None:
    expected = json.loads((FOLDER / "expected/refused.json").read_text())
    widen = json.loads((FOLDER / "fixtures/widen.json").read_text())
    with pytest.raises(BadRequest) as caught:
        start_chat_thread(ops_client(), _bindings()["agentId"], overrides=widen)
    err = caught.value
    assert err.status == expected["status"]
    assert err.code == expected["code"]
    field = (err.details or {}).get("field") if isinstance(err.details, dict) else None
    assert field == expected["field"]


def test_narrow_override_applies() -> None:
    expected = json.loads((FOLDER / "expected/narrowed.json").read_text())
    narrow = json.loads((FOLDER / "fixtures/narrow.json").read_text())
    question = json.loads((FOLDER / "fixtures/question.json").read_text())["message"]
    ops = ops_client()
    bindings = _bindings()
    kb_id = bindings.get("knowledgeId")
    thread = start_chat_thread(ops, bindings["agentId"], kb_ids=[kb_id] if kb_id else [])
    limits = thread_settings(ops, thread["id"]).get("limits") or {}
    allowed = limits.get("allowedModels") or []
    if allowed:
        narrow = {**narrow, "model": allowed[0]}
    if kb_id:
        narrow = {**narrow, "knowledgeBaseIds": [kb_id]}
    saved = patch_thread_settings(ops, thread["id"], narrow)
    effective = saved.get("effective") or {}
    assert READ_TOOL in (effective.get("toolsOff") or [])
    assert (effective.get("sources") or {}).get("toolsOff") == expected["source"]
    if allowed:
        assert effective.get("model") == allowed[0]
        assert (effective.get("sources") or {}).get("model") == expected["source"]
    if kb_id:
        assert effective.get("knowledgeBaseIds") == [kb_id]
        assert (effective.get("sources") or {}).get("knowledgeBaseIds") == expected["source"]
    result = send_chat(ops, thread["id"], question)
    reply = chat_reply(result)
    names = chat_tool_names(result)
    assert bool(reply) is expected["hasReply"]
    assert READ_TOOL not in names
    assert names == expected["called"]
    turn = result.get("settings") or {}
    assert READ_TOOL in (turn.get("toolsOff") or [])
    assert (turn.get("sources") or {}).get("toolsOff") == expected["source"]


def test_without_override_the_a3_read_tool_is_called() -> None:
    expected = json.loads((FOLDER / "expected/tool.json").read_text())
    question = json.loads((FOLDER / "fixtures/question.json").read_text())["message"]
    ops = ops_client()
    thread = start_chat_thread(ops, _bindings()["agentId"])
    result = send_chat(ops, thread["id"], question)
    names = chat_tool_names(result)
    assert bool(chat_reply(result)) is expected["hasReply"]
    assert expected["called"] in names
    assert READ_TOOL in names
