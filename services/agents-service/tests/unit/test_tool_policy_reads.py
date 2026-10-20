"""A tool's write policy read once per request (the Human Tasks list), by failure mode: the list asks tools-service once
per waiting write, so a long queue times out; a policy changed in tools-service is not seen by the next request."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from ops_agents.api.tool_access import one_read_per_tool, policy_of


class Tools:
    def __init__(self) -> None:
        self.asked: list[str] = []
        self.approvers = 1

    async def tool_policy(self, tool: str) -> dict[str, Any]:
        self.asked.append(tool)
        return {"access": "write", "approval": {"approvers": self.approvers}}


async def test_one_request_asks_once_per_tool_and_the_next_request_sees_a_changed_policy() -> None:
    tools = Tools()
    rt: Any = SimpleNamespace(tools=tools)
    with one_read_per_tool():
        for _ in range(30):
            await policy_of(rt, "place_hold")
            await policy_of(rt, "send_reply")
    assert tools.asked == ["place_hold", "send_reply"]
    tools.approvers = 2
    with one_read_per_tool():
        assert (await policy_of(rt, "place_hold")).approvers == 2
    assert (await policy_of(rt, "place_hold")).approvers == 2 and len(tools.asked) == 4, (
        "outside a request, ask each time"
    )
