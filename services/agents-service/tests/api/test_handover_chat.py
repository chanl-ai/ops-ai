"""A hand-over in a chat, through the chat route and the agent graph
(docs/design/agents-v2/automatic-mode-and-loop-kinds.md, "Hand-overs"): the conversation moves to the agent handed to,
each agent keeps its own loop state, and the next message is answered by the agent the conversation was left with."""

from __future__ import annotations

from typing import Any

from ops_agents.api.runs import config, resolve
from tests.api.test_action_roles import ADMIN, VIEWER
from tests.api.test_team_default_agent import (
    URL,
    Stack,
    move,
    say,
    stack,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    start,
)

HAND = 'call hand_over {"agentId": "ag_dispute", "message": "Dispute a card charge for C-1042"}'


async def test_a_hand_over_moves_the_conversation_and_keeps_each_agents_own_history(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    assert (await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)).status_code == 200
    # The seeded agent made a swarm agent that may hand to the disputes agent, as its spec would say.
    at = next(i for i, a in enumerate(rt.catalog.agents) if a.id == "ag_branch")
    rt.catalog.agents[at] = rt.catalog.agents[at].model_copy(
        update={"loop": {"kind": "swarm"}, "handoffs": ["ag_dispute"]}
    )
    thread = (await start(c, VIEWER))["id"]
    events = await say(c, thread, HAND, VIEWER)
    handed = [e for e in events if e["type"] == "handoff"]
    assert [(e["to"], e["message"]) for e in handed] == [("ag_dispute", "Dispute a card charge for C-1042")], events
    assert events[-1]["type"] == "done", events[-1]

    async def state() -> dict[str, Any]:
        _, graph = await resolve(rt, thread)
        return dict((await graph.aget_state(config(thread))).values)

    after = await state()
    assert after["active_agent"] == "ag_dispute", after.get("active_agent")
    told = after["loop_states"]["ag_dispute"][0]["content"]
    assert "Dispute a card charge for C-1042" in told and "call hand_over" not in told, told
    await say(c, thread, "Hello", VIEWER)
    again = await state()
    assert len(again["loop_states"]["ag_dispute"]) == 4, "the next message went to the agent handed to"
    assert len(again["loop_states"]["ag_branch"]) == 2, "the first agent's own history is kept as it was"


async def test_a_hand_over_to_another_teams_agent_is_refused(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    assert (await c.put(URL, json={"agentId": "ag_branch"}, headers=ADMIN)).status_code == 200
    await move(rt, "ag_fraud", "team_fraud")  # a viewer of team_ops may not chat with it
    at = next(i for i, a in enumerate(rt.catalog.agents) if a.id == "ag_branch")
    rt.catalog.agents[at] = rt.catalog.agents[at].model_copy(
        update={"loop": {"kind": "swarm"}, "handoffs": ["ag_fraud"]}
    )
    thread = (await start(c, VIEWER))["id"]
    events = await say(c, thread, 'call hand_over {"agentId": "ag_fraud", "message": "Check this card"}', VIEWER)
    assert not [e for e in events if e["type"] == "handoff"], events
    _, graph = await resolve(rt, thread)
    assert (await graph.aget_state(config(thread))).values.get("active_agent") == "ag_branch"
