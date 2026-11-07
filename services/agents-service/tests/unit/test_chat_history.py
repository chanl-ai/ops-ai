"""What a follow-up turn is given from the reply before it, by failure mode: the skill it loaded is lost, so it loads
again; the records it read are lost, so it searches again; a failed call or the kernel's own tools are passed on as
reads; a large result is passed whole."""

from __future__ import annotations

from typing import Any

from ops_agents.api.chat_history import READ_CHARS, history_entry
from ops_agents.graphs.agent_wrapper import _earlier  # pyright: ignore[reportPrivateUsage]
from ops_contracts.chat import ChatMessage, LoadedSkill, ToolCall


def call(name: str, output: Any, status: str = "success") -> ToolCall:
    return ToolCall(id=name, name=name, server="s", input={"q": "x"}, output=output, status=status, duration_ms=1)  # type: ignore[arg-type]


def test_a_reply_passes_on_its_skill_and_its_successful_reads_only() -> None:
    reply = ChatMessage(
        id="m2",
        role="assistant",
        content="Update Education savings, or open a new one?",
        at="t",
        skills=[LoadedSkill(skill_id="sk_opp", name="Salesforce opportunities", version=2, matched="log")],
        tool_calls=[
            call("load_skill", {"body": "..."}),
            call("salesforce_query", {"records": [{"Id": "006EDU", "Name": "Education savings"}]}),
            call("salesforce_search", {"error": "down"}, status="failed"),
            call("salesforce_get_record", {"Description": "x" * 5000}),
        ],
    )
    history = [{"role": "user", "content": "Log my meeting"}, history_entry(reply)]
    carried, reads = _earlier(history)
    assert carried == [{"skillId": "sk_opp", "version": 2, "name": "Salesforce opportunities", "matched": "log"}]
    assert len(reads) == 2 and "006EDU" in reads[0] and reads[0].startswith("salesforce_query")
    assert len(reads[1]) == READ_CHARS
    assert history_entry(ChatMessage(id="m1", role="user", content="hi", at="t")) == {"role": "user", "content": "hi"}
