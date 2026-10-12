# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# langgraph.graph ships without complete type information (no stubs; StateGraph.add_node is partially Unknown).
"""An agent as a graph (one runtime): the kernel turn, a human approval when a gated tool stops it, and the resumed
turn. Split into nodes because LangGraph re-runs a node from its start on resume; only the approval node, which does
no work before interrupt(), runs twice."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from ops_agent_kernel.types import Resume, TranscriptMessage, TurnRequest
from ops_agents.activities.tools import fill
from ops_service_kit.ids import new_id

from .common import (
    GraphDeps,
    approval_token,
    interrupt_from_state,
    interrupt_to_state,
    kernel_turn,
    ports_with_workflows,
)


class AgentState(TypedDict):
    # Absent on a published agent's own graph, which is built for one agent.
    agent_id: NotRequired[str]
    message: str
    kb_ids: NotRequired[list[str]]
    messages: Annotated[list[dict[str, str]], operator.add]
    pending: NotRequired[dict[str, Any] | None]
    decision: NotRequired[dict[str, Any] | None]
    reply: NotRequired[str]
    tool_results: Annotated[list[dict[str, Any]], operator.add]
    # Set by a chat run: the transcript to answer from (earlier turns minus superseded ones) and who asked, which
    # the approval carries so the reviewer's requester check can refuse the asker.
    history: NotRequired[list[dict[str, str]]]
    requested_by: NotRequired[str]


def build(
    deps: GraphDeps, checkpointer: BaseCheckpointSaver[Any] | None, *, agent_id: str | None = None
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """`agent_id` fixes the agent, for the graph a publish registers as `agent:<id>`; without it the input names one."""

    def agent_of(state: AgentState, *, in_flight: bool = False):
        """The agent for a turn. A new turn needs it live; finishing one (the resume after an approval) may use the
        definition it started on even if the agent was paused since."""
        aid = agent_id or state.get("agent_id")
        agent = (deps.catalog.agent_in_flight(aid) if in_flight else deps.catalog.agent(aid)) if aid else None
        if agent is None:
            raise ValueError(f"Agent {aid} is not live, so it takes no new turns.")
        return agent

    async def agent(state: AgentState) -> dict[str, Any]:
        a = agent_of(state)
        ports, offers = await ports_with_workflows(deps, list(a.tools))
        source = state["history"] if "history" in state else state["messages"]
        transcript = [TranscriptMessage(m["role"], m["content"]) for m in source]  # pyright: ignore[reportArgumentType]
        req = TurnRequest(
            turn_id=new_id("turn"),
            run_id=new_id("run"),
            settings=deps.catalog.settings_for(a, deps.model_alias),
            tools=[*deps.catalog.grants_for(a), *offers],
            transcript=transcript,
            user_turn=state["message"],
            kb_ids=state.get("kb_ids") or a.default_kb_ids,
        )
        result = await kernel_turn("agent", req, ports, deps.meter, deps.model_alias)
        return {
            "messages": [{"role": "user", "content": state["message"]}, {"role": "assistant", "content": result.text}],
            "pending": interrupt_to_state(result.interrupt) if result.interrupt else None,
            "reply": result.text,
        }

    async def approval(state: AgentState) -> dict[str, Any]:
        p = state.get("pending") or {}
        definition = deps.catalog.tool(p["tool"])
        tpl = definition.approval if definition else None
        values = {k: str(v) for k, v in p["input"].items()}
        decision = interrupt(
            {
                "kind": "approval",
                "review_id": f"REV-{p['action_id'][:6].upper()}",
                "tool": p["tool"],
                "action": fill(tpl.action, values) if tpl else p["needed"],
                "input": p["input"],
                "input_hash": p["input_hash"],
                "moves_money": p["access"] == "money_movement",
                "reviewers": tpl.reviewers if tpl else None,
                "call": {"tool": p["tool"], "input": p["input"], "step": p["key"]},
                "server": p["server"],
                "access": p["access"],
                "action_id": p["action_id"],
                "needed": p["needed"],
                **({"requested_by": asker} if (asker := state.get("requested_by")) else {}),
            }
        )
        return {"decision": decision}

    async def resume(state: AgentState) -> dict[str, Any]:
        a = agent_of(state, in_flight=True)
        ports, offers = await ports_with_workflows(deps, list(a.tools))
        d = state.get("decision") or {}
        approved = d.get("decision") == "approved"
        req = TurnRequest(
            turn_id=new_id("turn"),
            run_id=new_id("run"),
            settings=deps.catalog.settings_for(a, deps.model_alias),
            tools=[*deps.catalog.grants_for(a), *offers],
            resume=Resume(
                interrupt=interrupt_from_state(state.get("pending") or {}),
                decision="approved" if approved else "rejected",
                reason=d.get("reason"),
                # The review service's signed token when there is one. Without a gateway the local executor only needs
                # to see that a decision was made, which the fallback marker says.
                approval_token=(approval_token(d) or f"approval:{d.get('step_up_token') or 'policy'}")
                if approved
                else None,
            ),
        )
        result = await kernel_turn("resume", req, ports, deps.meter, deps.model_alias)
        return {
            "messages": [{"role": "assistant", "content": result.text}],
            "pending": interrupt_to_state(result.interrupt) if result.interrupt else None,
            "decision": None,
            "reply": result.text,
            "tool_results": [{"tool": c.tool, "status": c.status, "output": c.output} for c in result.tool_calls],
        }

    def after_turn(state: AgentState) -> Literal["approval", "__end__"]:
        return "approval" if state.get("pending") else "__end__"

    g = StateGraph(AgentState)
    g.add_node("agent", agent)
    g.add_node("approval", approval)
    g.add_node("resume", resume)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", after_turn, ["approval", END])
    g.add_edge("approval", "resume")
    g.add_conditional_edges("resume", after_turn, ["approval", END])
    return g.compile(checkpointer=checkpointer, name=f"agent:{agent_id}" if agent_id else "agent_wrapper")
