"""Hand-overs, by the two failure modes of the acceptance table (docs/design/agents-v2/automatic-mode-and-loop-kinds.md,
rows 5 and 6): a hand-over loses the thread, and hand-overs ping-pong forever. Each turn runs the real kernel."""

from __future__ import annotations

from typing import Any

from ops_agent_kernel.events import TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.testing import Reply, ToolCall
from ops_agent_kernel.types import LoopSettings, ToolGrant, TurnRequest, TurnResult
from ops_agents.graphs.handovers import Handovers, HandoverTools, grants, refused_at, run_with_handovers
from ops_service_kit.http import Json
from tests.conftest import model_on, trailing_tool_results
from tests.unit.test_kernel import SETTINGS, FixedKnowledge

LOOKUP = ToolGrant("get_card", "cards", "Read a card", "read", {"type": "object"})
SECRET = "card-ledger-row-77341"


class Cards:
    async def execute(self, tool: str, arguments: Json, *, key: str, approval_token: str | None) -> ToolOutcome:
        return ToolOutcome(True, {"ledger": SECRET})


async def turn_on(scripts: dict[str, Any], targets: dict[str, str]) -> Any:
    async def turn(agent: str, said: str, h: Handovers) -> TurnResult:
        others = {a: n for a, n in targets.items() if a != agent}
        tools = HandoverTools(Cards(), h, agent, frozenset(others))
        req = TurnRequest(
            "t", f"th_{agent}", SETTINGS, [LOOKUP, *grants(others)], user_turn=said, loop=LoopSettings("swarm")
        )
        events = [e async for e in run_turn(req, KernelPorts(model_on(scripts[agent]), tools, FixedKnowledge([])))]
        assert isinstance(events[-1], TurnFinished)
        return events[-1].result

    return turn


async def test_the_receiving_agent_starts_from_the_notes_and_the_message_not_the_previous_exchange() -> None:
    def intake(messages: list[Json], tools: list[Json]) -> Reply | str:
        if not trailing_tool_results(messages):
            return Reply(tool_calls=[ToolCall("add_note", {"text": "Customer C-1042"}), ToolCall("get_card", {})])
        if len(messages) < 6:
            return Reply(tool_calls=[ToolCall("hand_over", {"agentId": "ag_desk", "message": "Dispute a charge"})])
        return "The disputes desk takes over."

    seen: list[list[Json]] = []

    def desk(messages: list[Json], tools: list[Json]) -> str:
        seen.append(messages)
        return "I can open the dispute."

    h = Handovers(max_handoffs=4)
    turn = await turn_on({"ag_intake": intake, "ag_desk": desk}, {"ag_intake": "Intake", "ag_desk": "Disputes"})
    out = await run_with_handovers("ag_intake", "I want to dispute a charge", turn, h)
    assert [a for a, _ in out] == ["ag_intake", "ag_desk"] and out[-1][1].text == "I can open the dispute."
    first = str(seen[0])
    assert "Customer C-1042" in first and "Dispute a charge" in first, first
    assert SECRET not in first, "the previous agent's tool results stay with it"


async def test_the_fifth_hand_over_in_one_message_is_refused() -> None:
    told: list[str] = []
    names = ["ag_a", "ag_b", "ag_c", "ag_d", "ag_e", "ag_f"]

    def passes_on(nxt: str) -> Any:
        def script(messages: list[Json], tools: list[Json]) -> Reply | str:
            if back := trailing_tool_results(messages):
                told.append(str(back))
                return "Over to the next desk."
            return Reply(tool_calls=[ToolCall("hand_over", {"agentId": nxt, "message": "Yours"})])

        return script

    scripts = {a: passes_on(names[(i + 1) % len(names)]) for i, a in enumerate(names)}
    h = Handovers(max_handoffs=4)
    out = await run_with_handovers("ag_a", "Help", await turn_on(scripts, {a: a for a in names}), h)
    assert [a for a, _ in out] == ["ag_a", "ag_b", "ag_c", "ag_d", "ag_e"] and h.count == 4
    assert refused_at(4) in told[-1], told[-1]
