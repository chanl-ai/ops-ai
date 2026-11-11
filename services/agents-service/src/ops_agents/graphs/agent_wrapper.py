# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false
# langgraph.graph ships without complete type information (no stubs; StateGraph.add_node is partially Unknown).
"""An agent as a graph (one runtime): the kernel turn, a human approval when a gated tool stops it, and the resumed
turn. Split into nodes because LangGraph re-runs a node from its start on resume; only the approval node, which does
no work before interrupt(), runs twice."""

from __future__ import annotations

import operator
from collections.abc import Mapping
from dataclasses import replace
from typing import Annotated, Any, Literal, NotRequired, TypedDict, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from ops_agent_kernel.types import AttachedFile, Passage, Resume, ToolGrant, TranscriptMessage, TurnRequest
from ops_agents.activities.attachments import ATTACHMENT_KB
from ops_agents.activities.catalog import AgentDefinition
from ops_agents.activities.gateway import LIVE, TEST, acting_as, current_run_context
from ops_agents.activities.overrides import limits_for
from ops_agents.activities.tool_directory import CatalogTools, OperationRef
from ops_agents.activities.tools import fill
from ops_agents.domain.accounts import chosen_accounts
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
    with_apps,
    with_memory,
)

# How many earlier lines of reads a turn is given, newest kept.
EARLIER_READS = 8


def _earlier(source: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """The skills the last reply loaded and the reads of the last two replies, for a follow-up to build on."""
    replies = [m for m in source if m.get("role") == "assistant"]
    carried = list(cast(list[dict[str, Any]], replies[-1].get("skills") or [])) if replies else []
    reads = [str(r) for m in replies[-2:] for r in cast(list[Any], m.get("reads") or [])]
    return carried, reads[-EARLIER_READS:]


def turn_environment(state: Mapping[str, Any]) -> str:
    """The kind of run a turn's tool calls are made in: a test chat's test, a live chat's live,
    unless the run it serves is a test run."""
    if state.get("test_agent") is not None:
        return TEST
    return current_run_context().environment or LIVE


class AgentState(TypedDict):
    # Absent on a published agent's own graph, which is built for one agent.
    agent_id: NotRequired[str]
    # A deployment's pinned version; absent serves the live version.
    agent_version: NotRequired[int]
    # A test thread's agent: the newest version, draft included, as the chat route built it for this message.
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
    # Each assistant entry may carry the skills that turn loaded (`skills`) and lines for what it read (`reads`).
    history: NotRequired[list[dict[str, Any]]]
    requested_by: NotRequired[str]
    # The apps the person answered "Allow for this chat" for (module id, else server name): kept by the thread's
    # checkpoint, so later turns of this chat only stop asking before their changes.
    writes_allowed: NotRequired[list[str]]
    # Set by a chat run: the settings the override resolver allowed for this turn, and the raw overrides it
    # resolved them from, kept on the run as they were sent.
    settings: NotRequired[dict[str, Any]]
    thread_overrides: NotRequired[dict[str, Any]]
    overrides: NotRequired[dict[str, Any]]
    # Passages of the files attached in this thread, capped by the chat route; searched before the knowledge bases.
    attached_passages: NotRequired[list[dict[str, Any]]]
    # Every file attached in this thread, {fileId, name, unread?}: named to the model whether or not it was read.
    attached_files: NotRequired[list[dict[str, Any]]]


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
        carried, reads = _earlier(cast(list[dict[str, Any]], source))
        replies = [m for m in cast(list[dict[str, Any]], source) if m.get("role") == "assistant"]
        open_plan = cast(dict[str, Any] | None, replies[-1].get("plan")) if replies else None
        effective = _effective(state)
        grants = _kb_grants(a, deps.model_alias, effective)
        attached = [
            Passage(p["documentId"], p["title"], p["section"], "attached", p["text"], ATTACHMENT_KB, p.get("page"))
            for p in state.get("attached_passages") or []
        ]
        req = TurnRequest(
            turn_id=new_id("turn"),
            run_id=new_id("run"),
            settings=await with_apps(
                deps, await with_memory(deps, deps.catalog.settings_for(a, deps.model_alias, effective), a.id), a.id
            ),
            tools=[*await asked(state, _switched_on(await agent_grants(deps, a), effective)), *offers],
            transcript=transcript,
            carried_skills=carried,
            earlier_reads=reads,
            carried_plan=open_plan,
            user_turn=state["message"],
            kb_ids=_granted(state, grants),
            all_team_knowledge=a.all_team_knowledge,
            attached=attached,
            attachments=[
                AttachedFile(str(f["fileId"]), str(f["name"]), f.get("unread"))
                for f in state.get("attached_files") or []
            ],
            knowledge_withdrawn=bool(state.get("kb_ids")) and not _granted(state, grants) and not attached,
            # A conversation that named knowledge bases, or attached a file, asked for knowledge; one that named none
            # gets the agent's passages when they match, and finding none is not a no-answer.
            knowledge_asked=bool(state.get("kb_ids")) or bool(attached),
        )
        # The agent is the actor of every call its turn makes, in the gateway's log, on the accounts it and the chat
        # chose.
        with acting_as(f"agent:{a.id}", turn_environment(state), turn_accounts(a, state)):
            result = await kernel_turn("agent", req, ports, deps.meter, deps.model_alias)
        return {
            "messages": [{"role": "user", "content": state["message"]}, {"role": "assistant", "content": result.text}],
            "pending": interrupt_to_state(result.interrupt) if result.interrupt else None,
            "reply": result.text,
        }

    async def operations() -> list[OperationRef]:
        return await (deps.tools or CatalogTools(deps.catalog)).operations()

    async def allowed_now(state: AgentState, decision: dict[str, Any] | None) -> list[str]:
        """The app the decision being resumed answered "Allow for this chat" for; none for any other answer."""
        d = decision or {}
        if d.get("decision") != "approved" or not d.get("for_chat"):
            return []
        tool = (state.get("pending") or {}).get("tool")
        return [app_of(o) for o in await operations() if o.name == tool][:1]

    async def asked(state: AgentState, grants: list[ToolGrant], allowed: list[str] | None = None) -> list[ToolGrant]:
        """The grants with each write its app asks the person about made to pause (ask_first)."""
        return ask_first(
            grants,
            await operations(),
            person=state.get("requested_by"),
            live=turn_environment(state) == LIVE,
            allowed=[*(state.get("writes_allowed") or []), *(allowed or [])],
        )

    async def approval(state: AgentState) -> dict[str, Any]:
        p = state.get("pending") or {}
        op = next((o for o in await operations() if o.name == p["tool"]), None)
        # The person in the chat answers this one themselves (Allow, Deny, Allow for this chat): their app asks before
        # changes and no reviewer's approval holds the write.
        asks = bool(state.get("requested_by")) and asks_person(op, live=turn_environment(state) == LIVE)
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
                **({"ask_first": True, "app": app_of(op)} if asks and op is not None else {}),
                # The role whose holders approve this write; nobody else, and never the asker.
                **({"reviewer_role": op.reviewer_role} if op is not None and not asks and op.reviewer_role else {}),
            }
        )
        return {"decision": decision}

    async def resume(state: AgentState) -> dict[str, Any]:
        a = agent_of(state, in_flight=True)
        ports, offers = await ports_with_workflows(deps, list(a.tools), agent_id=a.id)
        d = state.get("decision") or {}
        approved = d.get("decision") == "approved"
        now = await allowed_now(state, d)
        effective = _effective(state)
        req = TurnRequest(
            turn_id=new_id("turn"),
            run_id=new_id("run"),
            settings=await with_apps(
                deps, await with_memory(deps, deps.catalog.settings_for(a, deps.model_alias, effective), a.id), a.id
            ),
            tools=[*await asked(state, _switched_on(await agent_grants(deps, a), effective), now), *offers],
            # The same bases as the turn it resumes, so a search after the approval keeps to them.
            kb_ids=_granted(state, _kb_grants(a, deps.model_alias, effective)),
            all_team_knowledge=a.all_team_knowledge,
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
        with acting_as(f"agent:{a.id}", turn_environment(state), turn_accounts(a, state)):
            result = await kernel_turn("resume", req, ports, deps.meter, deps.model_alias)
        return {
            "messages": [{"role": "assistant", "content": result.text}],
            "pending": interrupt_to_state(result.interrupt) if result.interrupt else None,
            "decision": None,
            "writes_allowed": [*(state.get("writes_allowed") or []), *now],
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


def turn_accounts(agent: AgentDefinition, state: Mapping[str, Any]) -> dict[str, str]:
    """The account each app's calls use in a turn: the chat's pick (its thread's `accounts`) over the agent's own."""
    chosen = cast(dict[str, Any], (state.get("thread_overrides") or {}).get("accounts") or {})
    return chosen_accounts(agent=agent.accounts, chat=chosen)


def app_of(op: OperationRef) -> str:
    """The app an "Allow for this chat" answer covers: the operation's module, else its server's name."""
    return op.module_id or op.module_name


def asks_person(op: OperationRef | None, *, live: bool) -> bool:
    """Whether a write's wait is the person in chat's to answer first (Allow / Deny / Allow for this chat): the tool
    waits (`requiresApproval`), the team, app or tool chose "ask the person" over a reviewer, and it does not land on a
    test account (a test turn on an app that has one)."""
    return bool(
        op
        and op.access not in ("read", "workflow")
        and op.requires_approval
        and op.answer == "person"
        and (live or not op.test_account)
    )


def ask_first(
    grants: list[ToolGrant], ops: list[OperationRef], *, person: str | None, live: bool, allowed: list[str]
) -> list[ToolGrant]:
    """The turn's grants with the waits the person in chat does not need to answer lifted: an app they allowed for
    this chat, and a test turn on an app with a test account. Every other wait stays as the tool declares it, so the
    kernel stops before it and the chat draws the card. A turn with nobody in it (a workflow's or a schedule's agent)
    keeps its grants as they are."""
    if not person:
        return grants
    by_name = {o.name: o for o in ops}
    return [
        replace(g, requires_approval=False)
        if g.requires_approval
        and (op := by_name.get(g.name)) is not None
        and op.access not in ("read", "workflow")
        and (app_of(op) in allowed or (not live and op.test_account))
        else g
        for g in grants
    ]


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
