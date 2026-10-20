"""The call log's rows (c-070 T007), by failure mode: an approved write that does not say who approved it, and a chat
call whose run cannot be told from a workflow's."""

from __future__ import annotations

from typing import Any

from ops_tools.modules.executions import call_row


def _row(**over: Any) -> dict[str, Any]:
    return {
        "id": "gwc_1", "created_at": "2026-10-17T10:00:00Z", "tool": "place_hold", "access": "write",
        "outcome": "ok", "latency_ms": 12, "sub": "user:j.richardson@northfieldbank.com", "act": "agent:ag_branch",
        "thread_id": "th_abc", "step": "s1", "approvers": [], "approval_token_id": None, "decision": "allow",
        "reasons": [], "effect": True, **over,
    }  # fmt: skip


def test_an_approved_write_names_who_approved_it() -> None:
    row = call_row(_row(approvers=["Maya Okafor"], approval_token_id="tok_1"), {}, None)
    assert row["approval"] == {"kind": "person", "tokenId": "tok_1", "by": "Maya Okafor"}


def test_a_chat_call_carries_its_thread_and_no_workflow() -> None:
    row = call_row(_row(access="read", tool="get_account"), {}, None)
    assert (row["runId"], row["workflowId"], row["agentSlug"]) == ("th_abc", "", "ag_branch")
    assert row["approval"] == {"kind": "none"}
