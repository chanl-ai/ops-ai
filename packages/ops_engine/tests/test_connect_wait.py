"""A run that needs its person's own account of an app waits for them to connect, by failure mode: the
step fails as if the system had refused it; the run waits on something nobody reports, or on the wrong person's key;
connecting does not send the call again; and a call still refused after the person connected waits forever instead of
failing with the reason. A refusal for nobody behind the call is setup to fix, so it still fails at once."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from ops_engine.compiler import channel
from ops_engine.journal import MemoryJournal
from ops_engine.ports import AS_TEAM_ACCOUNT, ToolResult

from .test_compiler import PAYLOAD, FakeTools, build, config

KEY = "con_crm:production:usr_james"


def not_linked(reason: str = "not_connected") -> dict[str, Any]:
    """The gateway's refusal for a person with no account of their own (tools-service auth._not_linked)."""
    details: dict[str, Any] = {"connectionId": "con_crm", "connection": "CRM", "reason": reason}
    if reason not in ("needs_person", "no_person"):
        details["connectedEvent"] = {"name": "app_account.connected", "key": KEY}
        details["teamAccount"] = True
    message = "CRM needs James to connect their own account."
    return {"error": {"code": "CONNECTION_NOT_LINKED", "message": message, "details": details}}


class NeedsAccount(FakeTools):
    """Refuses until `refusals` calls have been made, then answers; a call on the team account always answers."""

    def __init__(self, refusals: int, reason: str = "not_connected") -> None:
        super().__init__()
        self.refusals, self.reason = refusals, reason
        self.as_team: list[bool] = []

    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        self.calls.append(key)
        self.as_team.append(AS_TEAM_ACCOUNT.get())
        if len(self.calls) <= self.refusals and not AS_TEAM_ACCOUNT.get():
            return ToolResult(False, not_linked(self.reason), reason="CRM needs James to connect their own account.")
        return ToolResult(True, {"id": input.get("customer_id"), "name": "Ana"})


async def test_the_run_waits_for_its_person_to_connect_and_then_sends_the_call() -> None:
    tools, saver = NeedsAccount(refusals=1), InMemorySaver()
    g = build(tools, MemoryJournal(), saver)
    await g.ainvoke({"input": PAYLOAD}, config("c1"), durability="sync")
    [paused] = (await g.aget_state(config("c1"))).interrupts
    wait = paused.value
    assert (wait["kind"], wait["event"], wait["key"]) == ("external", "app_account.connected", KEY), wait
    assert wait["title"] == "Connect your CRM account to continue" and wait["app"] == "CRM", wait
    assert wait["timeoutSeconds"] == 0, "a run waiting for a person is never failed by a time limit"
    await g.ainvoke(Command(resume={"event": {"connectionId": "con_crm"}}), config("c1"), durability="sync")
    state = await g.aget_state(config("c1"))
    assert state.values[channel("lookup")]["port"] == "ok", state.values[channel("lookup")]
    assert tools.calls == ["c1:lookup:1:1", "c1:lookup:1:1"], "the same call, sent again under its own key"


async def test_a_call_still_refused_after_the_person_connected_fails_with_the_reason() -> None:
    tools, saver = NeedsAccount(refusals=3), InMemorySaver()
    g = build(tools, MemoryJournal(), saver)
    await g.ainvoke({"input": PAYLOAD}, config("c2"), durability="sync")
    await g.ainvoke(Command(resume={"event": {"connectionId": "con_crm"}}), config("c2"), durability="sync")
    state = await g.aget_state(config("c2"))
    assert not state.interrupts and state.values[channel("failed")]["out"]["outcome"] == "tool_failed", state.values


async def test_a_refusal_for_nobody_behind_the_call_fails_at_once() -> None:
    tools = NeedsAccount(refusals=5, reason="no_person")
    g = build(tools, MemoryJournal(), InMemorySaver())
    await g.ainvoke({"input": PAYLOAD}, config("c3"), durability="sync")
    state = await g.aget_state(config("c3"))
    assert not state.interrupts and state.values[channel("failed")]["out"]["outcome"] == "tool_failed"
    assert tools.calls == ["c3:lookup:1:1"]


async def test_run_as_the_team_account_sends_the_call_acting_for_nobody() -> None:
    tools, saver = NeedsAccount(refusals=5), InMemorySaver()
    g = build(tools, MemoryJournal(), saver)
    await g.ainvoke({"input": PAYLOAD}, config("c4"), durability="sync")
    [paused] = (await g.aget_state(config("c4"))).interrupts
    assert paused.value["teamAccount"] is True, "the task says the team account may stand in"
    await g.ainvoke(Command(resume={"teamAccount": {"by": "p.shah@bank.example"}}), config("c4"), durability="sync")
    state = await g.aget_state(config("c4"))
    assert state.values[channel("lookup")]["port"] == "ok", state.values[channel("lookup")]
    assert tools.as_team[-1] is True and AS_TEAM_ACCOUNT.get() is False, tools.as_team
