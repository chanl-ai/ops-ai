# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# langgraph.graph ships without complete type information (no stubs; StateGraph.add_node is partially Unknown).
"""An agent as a graph (one runtime): the kernel turn, a human approval when a gated tool stops it, and the resumed
turn. Split into nodes because LangGraph re-runs a node from its start on resume; only the approval node, which does
no work before interrupt(), runs twice."""

from __future__ import annotations

import operator
from collections.abc import Mapping
from dataclasses import replace
from typing import Annotated, Any, Literal, NotRequired, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from ops_agent_kernel.types import Passage, Resume, ToolGrant, TranscriptMessage, TurnRequest
from ops_agents.activities.attachments import WithAttachments
from ops_agents.activities.catalog import AgentDefinition
from ops_agents.activities.gateway import PRODUCTION, TEST, acting_as, current_run_context
from ops_agents.activities.overrides import limits_for
from ops_agents.activities.tools import fill
from ops_contracts.chat import EffectiveSettings
from ops_service_kit.ids import new_id

from .common import (
    GraphDeps,
    agent_grants,
    approval_token,
    interrupt_from_state,
    interrupt_to_state,
    kernel_turn,
    needs_step_up,
    ports_with_workflows,
    with_memory,
)


def turn_environment(state: Mapping[str, Any]) -> str:
    """Which connection environment a turn's tool calls use (c-330): a test chat's test, a live chat's production,
    unless the run it serves is a test run."""
    if state.get("test_agent") is not None:
        return TEST
    return current_run_context().environment or PRODUCTION


class AgentState(TypedDict):
    # Absent on a published agent's own graph, which is built for one agent.
    agent_id: NotRequired[str]
    # A deployment's pinned version (c-117); absent serves the live version.
    agent_version: NotRequired[int]
    # A test thread's agent (c-284): the newest version, draft included, as the chat route built it for this message.
    # Kept on the run, so the resume after an approval serves the same definition, whatever is live by then.
    test_agent: NotRequired[dict[str, Any]]
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
    # Set by a chat run (c-071): the settings the override resolver allowed for this turn, and the raw overrides it
    # resolved them from, kept on the run as they were sent.
    settings: NotRequired[dict[str, Any]]
    thread_overrides: NotRequired[dict[str, Any]]
    overrides: NotRequired[dict[str, Any]]
    # Passages of the files attached in this thread, capped by the chat route; searched before the knowledge bases.
    attached_passages: NotRequired[list[dict[str, Any]]]


def build(
    deps: GraphDeps, checkpointer: BaseCheckpointSaver[Any] | None, *, agent_id: str | None = None
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """`agent_id` fixes the agent, for the graph a publish registers as `agent:<id>`; without it the input names one."""

    def agent_of(state: AgentState, *, in_flight: bool = False):
        """The agent for a turn. A new turn needs it live; finishing one (the resume after an approval) may use the
        definition it started on even if the agent was paused since."""
        if (snapshot := state.get("test_agent")) is not None:
            return AgentDefinition.model_validate(snapshot)
        aid = agent_id or state.get("agent_id")
        pinned = state.get("agent_version")
        # A pinned version serves a new turn only while the agent is live: a pause stops widget turns too.
        live = in_flight or (aid is not None and deps.catalog.agent(aid) is not None)
        if aid and pinned is not None and live and (at := deps.catalog.agent_at(aid, pinned)) is not None:
            return at
        agent = (deps.catalog.agent_in_flight(aid) if in_flight else deps.catalog.agent(aid)) if aid else None
        if agent is None:
            raise ValueError(f"Agent {aid} is not live, so it takes no new turns.")
        return agent

    async def agent(state: AgentState) -> dict[str, Any]:
        a = agent_of(state)
        ports, offers = await ports_with_workflows(deps, list(a.tools), agent_id=a.id)
        source = state["history"] if "history" in state else state["messages"]
        transcript = [TranscriptMessage(m["role"], m["content"]) for m in source]  # pyright: ignore[reportArgumentType]
        effective = _effective(state)
        grants = _kb_grants(a, deps.model_alias, effective)
        attached = [
            Passage(p["documentId"], p["title"], p["section"], "attached", p["text"], "attachment", p.get("page"))
            for p in state.get("attached_passages") or []
        ]
        if attached:
            ports = replace(ports, knowledge=WithAttachments(ports.knowledge, attached))
        req = TurnRequest(
            turn_id=new_id("turn"),
            run_id=new_id("run"),
            settings=await with_memory(deps, deps.catalog.settings_for(a, deps.model_alias, effective), a.id),
            tools=[*_switched_on(await agent_grants(deps, a), effective), *offers],
            transcript=transcript,
            user_turn=state["message"],
            kb_ids=[*_granted(state, grants), *(["attachment"] if attached else [])],
            knowledge_withdrawn=bool(state.get("kb_ids")) and not _granted(state, grants) and not attached,
            # A conversation that named knowledge bases, or attached a file, asked for knowledge; one that named none
            # gets the agent's passages when they match, and finding none is not a no-answer.
            knowledge_asked=bool(state.get("kb_ids")) or bool(attached),
        )
        # The agent is the actor of every call its turn makes, in the gateway's log.
        with acting_as(f"agent:{a.id}", turn_environment(state)):
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
                "step_up": await needs_step_up(deps, p["tool"]),
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
        ports, offers = await ports_with_workflows(deps, list(a.tools), agent_id=a.id)
        d = state.get("decision") or {}
        approved = d.get("decision") == "approved"
        effective = _effective(state)
        req = TurnRequest(
            turn_id=new_id("turn"),
            run_id=new_id("run"),
            settings=await with_memory(deps, deps.catalog.settings_for(a, deps.model_alias, effective), a.id),
            tools=[*_switched_on(await agent_grants(deps, a), effective), *offers],
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
        with acting_as(f"agent:{a.id}", turn_environment(state)):
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


def _effective(state: AgentState) -> EffectiveSettings | None:
    raw = state.get("settings")
    return EffectiveSettings.model_validate(raw) if raw else None


def _switched_on(grants: list[ToolGrant], effective: EffectiveSettings | None) -> list[ToolGrant]:
    """The agent's grants less the ones the person switched off; nothing is ever added here."""
    off = set(effective.tools_off) if effective else set[str]()
    return [g for g in grants if g.name not in off]


def _kb_grants(agent: AgentDefinition, runtime_alias: str, effective: EffectiveSettings | None) -> list[str]:
    """The bases a turn may search. Knowledge chosen through overrides may be any base the agent's limits allow; the
    bases picked when the thread started, or none, are cut to the agent's defaults as they are now."""
    chosen = effective is not None and effective.sources.get("knowledgeBaseIds") in ("thread", "turn")
    return list(limits_for(agent, runtime_alias).allowed_knowledge_base_ids) if chosen else list(agent.default_kb_ids)


def _granted(state: AgentState, grants: list[str]) -> list[str]:
    """The knowledge bases this turn searches: the thread's choice cut to the agent's grants as they are now, since
    kb-service searches whatever ids it is sent. A thread whose every choice was taken away searches none, never all
    of the agent's; a run that names none searches all the agent holds."""
    if "kb_ids" not in state:
        return list(grants)
    return [k for k in state["kb_ids"] if k in grants]
