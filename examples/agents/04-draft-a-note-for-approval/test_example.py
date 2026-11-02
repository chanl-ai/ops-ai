import json
import sys
from pathlib import Path

import pytest

FOLDER = Path(__file__).resolve().parent
sys.path.insert(0, str(FOLDER.parents[1] / "_lib"))
from folder import (
    approve_write,
    chat_agent,
    chat_wait,
    customer_notes,
    folder_bindings,
    mint_write_token,
    ops_client,
    write_calls,
)


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


def _allowed(rows: list[dict]) -> list[dict]:
    return [row for row in rows if str(row.get("decision") or "") == "allow"]


def test_reject_leaves_no_write() -> None:
    expected = json.loads((FOLDER / "expected/rejected.json").read_text())
    ops = ops_client()
    waiting = chat_wait(ops, _chat("reject.json"))
    call = waiting["call"]
    assert waiting["payload"].get("kind") == "approval", waiting
    assert call.get("tool") == expected["called"]
    approve_write(ops, waiting["threadId"], "rejected")
    rows = write_calls(ops, waiting["threadId"])
    assert _allowed(rows) == []
    assert expected["wrote"] is False


def test_approve_writes_with_exact_input_token() -> None:
    expected = json.loads((FOLDER / "expected/approved.json").read_text())
    ops = ops_client()
    waiting = chat_wait(ops, _chat("approve.json"))
    call = waiting["call"]
    assert call.get("tool") == expected["called"], waiting
    token = mint_write_token(ops, waiting["threadId"])
    assert token.get("approvalToken"), token
    assert token.get("inputHash"), token
    approve_write(ops, waiting["threadId"], "approved")
    rows = _allowed(write_calls(ops, waiting["threadId"]))
    assert rows, rows
    assert any(row.get("approvalTokenId") for row in rows) is expected["hasToken"]
    assert expected["wrote"] is True


def test_changed_input_after_approve_keeps_the_exact_call() -> None:
    expected = json.loads((FOLDER / "expected/changed.json").read_text())
    fixture = json.loads((FOLDER / "fixtures/changed.json").read_text())
    ops = ops_client()
    waiting = chat_wait(ops, _chat("changed.json"))
    original = dict(waiting["call"].get("input") or {})
    assert waiting["call"].get("tool") == expected["called"]
    assert original.get("text")
    assert original.get("text") != fixture["changedText"]
    token = mint_write_token(ops, waiting["threadId"])
    assert token.get("inputHash"), token
    approve_write(
        ops,
        waiting["threadId"],
        "approved",
        inputs={**original, "text": fixture["changedText"]},
    )
    rows = _allowed(write_calls(ops, waiting["threadId"]))
    assert rows, rows
    customer_id = str(original.get("customer_id") or original.get("customerId") or "")
    texts = json.dumps(customer_notes(ops, customer_id))
    assert original["text"] in texts
    assert fixture["changedText"] not in texts
    assert expected["keptExactInput"] is True
    assert expected["wrote"] is True
