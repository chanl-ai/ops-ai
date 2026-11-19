"""Specialist agents as tools: the team's default agent asks another agent by calling `agent__<id>`, and that
agent answers with its own turn: its knowledge, tools, guardrails and approvals, for the same person.

Who may be asked is decided per turn, for the turn's verified caller (`TURN_PERSON`: a person, or the service
identity a run was started under): the agents the caller holds chat.run on, among the agent's own `agent:<id>` grants
and, for the team's default agent, every specialist. A turn with no person follows the rule every such turn does
(`child_runs.refused_with_no_person`): a scheduled run acts as its agent and asks the agents of its own team, a chat
turn resumed after a decision asks no one, and the thread's event log says which grants were withheld.

Each call carries a chain record (`ops_contracts.chain.ChainRecord`), kept on the specialist's thread: who the chain
runs for, the thread it started on, the agents on it and how deep it may go. The record decides who may be asked next,
for the offer and for the call: never an agent already on the path, never past its depth (one today, so a specialist
asks no one). A specialist
has no budget of its own: its model calls count against the thread the chain started on (store/usage.py), each one
checked before it runs (api/model_ledger.py). A specialist stopped at that budget returns what it has written, and the
asking agent reads `budget_reached`.
"""

from __future__ import annotations

import hashlib
from typing import Any

from langgraph.config import get_config

from ops_access import can
from ops_agent_kernel.ports import ToolOutcome
from ops_agent_kernel.types import ToolGrant
from ops_contracts.chain import ChainRecord, ChainRefusedError
from ops_service_kit import narrow
from ops_service_kit.errors import Forbidden, NotFound
from ops_service_kit.http import Json, JsonValue
from ops_service_kit.ids import new_id, now_iso

from ..graphs.common import AGENT_TOOL_PREFIX
from ..store.events import EventLog
from ..store.graphs import StoredThread
from ..store.team_defaults import TeamDefaults
from .agent_registry import registry
from .auth import caller_of
from .chat_threads import CHAT_GRAPH
from .child_runs import TURN_PERSON, refused_with_no_person, run_child
from .deps import Runtime
from .runs import config, graph_store, pending, resolve

QUESTION_SCHEMA: Json = {
    "type": "object",
    "properties": {"question": {"type": "string", "description": "The whole question, with what the person said"}},
    "required": ["question"],
}

# What the asking agent reads when the budget its chain shares is spent.
BUDGET_REACHED: Json = {
    "status": "budget_reached",
    "code": "chain_budget_reached",
    "error": "The budget this conversation shares with the agents it asks is spent.",
}


async def agent_team(rt: Runtime, agent_id: str) -> str | None:
    """The team that owns an agent of the caller's tenant; None for one with no team, which every team of that tenant
    may use. An id the caller's tenant does not hold is NotFound: the serving catalogue holds every tenant's agents."""
    owners = await registry(rt).tenant_owners({agent_id})
    if agent_id not in owners:
        raise NotFound(f"Agent {agent_id}")
    return owners[agent_id] or None


class AgentCalls:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    async def offers(self, agent_id: str) -> list[ToolGrant]:
        try:
            configurable = get_config().get("configurable") or {}
        except RuntimeError:
            return []  # not inside a graph run, so there is no turn to offer specialists to
        thread_id = str(configurable.get("thread_id") or "")
        if TURN_PERSON.get() is None and thread_id:
            await self._log_withheld(agent_id, thread_id, configurable.get("run_id"))
        return await self.offers_in(agent_id, thread_id)

    def _granted(self, agent_id: str) -> list[str]:
        """The agents `agent_id` holds as `agent:<id>` grants."""
        caller = self.rt.catalog.agent(agent_id)
        return [
            str(t).removeprefix("agent:")
            for t in (caller.tools if caller is not None else [])
            if str(t).startswith("agent:")
        ]

    async def _log_withheld(self, agent_id: str, thread_id: str, run_id: object) -> None:
        """Records, on the turn's thread, the agent grants the rule for a turn with no person withheld, and why."""
        granted = self._granted(agent_id)
        thread = await graph_store(self.rt).thread_row(thread_id) if granted else None
        if thread is None:
            return
        owners = await registry(self.rt).tenant_owners(set(granted))
        refused = {
            sid: why.code
            for sid in granted
            if sid in owners
            and (why := refused_with_no_person(thread, owners[sid] or None, f"agent {sid}")) is not None
        }
        if not refused:
            return
        await EventLog(graph_store(self.rt).engine).append(
            thread_id=thread_id,
            team_id=thread.team_id,
            run_id=str(run_id) if run_id else None,
            type_="agent_call_refused",
            # One thread gives one reason: its person is not known, or the agents are another team's.
            data={"agentId": agent_id, "withheld": list(refused), "code": next(iter(refused.values()))},
        )

    def _grant(self, a: Any) -> ToolGrant:
        return ToolGrant(
            name=f"{AGENT_TOOL_PREFIX}{a.id}",
            server="agents",
            description=f"Ask {a.name}, the {a.role}. It answers from its own knowledge and tools.",
            access="read",
            input_schema=QUESTION_SCHEMA,
        )

    def _chain(self, thread: StoredThread, agent_id: str, run_id: str | None = None) -> ChainRecord:
        """The chain the turn of `agent_id` on `thread` is on: the record written when its agent was asked, or, for a
        thread nobody asked, a chain that starts here."""
        meta = thread.meta_object()
        if not meta.get("calledBy"):
            asking = self.rt.catalog.agent(agent_id)
            person = TURN_PERSON.get()
            return ChainRecord.starting(
                agent_id=agent_id,
                version=asking.version if asking is not None else 0,
                # Its person, the service identity it runs under or, with no person, the agent itself.
                started_for=(person.email or caller_of(person).sub) if person is not None else f"agent:{agent_id}",
                thread_id=thread.id,
                run_id=run_id,
            )
        if meta.get("chain"):
            return ChainRecord.model_validate(meta["chain"])
        # A specialist's thread opened before chains were recorded: one call deep, as deep as chains then went.
        return ChainRecord(
            started_for=str(meta.get("startedFor") or ""),
            root_thread_id=str(meta.get("parentThreadId") or thread.id),
            path=[f"{meta['calledBy']}@v0", f"{agent_id}@v0"],
            depth=1,
        )

    async def offers_in(self, agent_id: str, thread_id: str) -> list[ToolGrant]:
        """Specialists `agent_id` may ask on this turn: its `agent:<id>` grants, and every specialist when it is the
        team's default, less the ones its chain refuses (already on the path, or past its depth) and the ones the
        turn's caller may not chat with. A turn with no person follows `refused_with_no_person`."""
        thread = await graph_store(self.rt).thread_row(thread_id) if thread_id else None
        if thread is None:
            return []
        person = TURN_PERSON.get()
        who = caller_of(person) if person is not None else None
        on = self._chain(thread, agent_id)
        out: list[ToolGrant] = []
        seen: set[str] = set()
        granted = self._granted(agent_id)
        # Every specialist is the default agent's to ask for a person only: with no person it holds its grants alone.
        if who is not None and await TeamDefaults(self.rt.db).agent(thread.team_id) == agent_id:
            granted = list(dict.fromkeys([*[a.id for a in self.rt.catalog.agents if a.id != agent_id], *granted]))
        # Only the agents of the thread's tenant: the catalogue holds every tenant's.
        owners = await registry(self.rt).tenant_owners({sid for sid in granted if sid != agent_id})
        for sid in granted:
            if sid == agent_id or sid in seen or sid not in owners:
                continue
            a = self.rt.catalog.agent(sid)
            if a is None:
                continue
            try:
                on.extended(a.id, a.version)
            except ChainRefusedError:
                continue
            if who is None:
                if refused_with_no_person(thread, owners[sid] or None, f"agent {a.name}") is not None:
                    continue
            # An agent with no team is open to every person of the tenant; a service or a key holds only what its
            # token lists, so it is checked there too.
            elif (team := owners[sid]) or who.kind != "person":
                try:
                    can(who, "chat", "run", team=team or None, what=a.name)
                except Forbidden:
                    continue
            seen.add(sid)
            out.append(self._grant(a))
        return out

    async def run(
        self, *, agent: str, arguments: Json, key: str, parent_thread_id: str, parent_run_id: str | None
    ) -> ToolOutcome:
        store = graph_store(self.rt)
        parent = await store.thread_row(parent_thread_id)
        assert parent is not None, "a tool runs inside its parent's run"
        parent_meta = parent.meta_object()
        caller = str(parent_meta.get("agentId") or "")
        if not caller and (parent.graph or "").startswith("agent:"):
            caller = parent.graph.removeprefix("agent:")
        person = TURN_PERSON.get()
        callee = self.rt.catalog.agent(agent)
        on = self._chain(parent, caller, parent_run_id)
        try:
            chain = on.extended(agent, callee.version if callee is not None else 0)
        except ChainRefusedError as e:
            return ToolOutcome(ok=False, output={"error": e.message, "code": e.code, "path": [*on.path]})
        # Checked again here, not only when offered: a model may name a tool it was never given.
        if f"{AGENT_TOOL_PREFIX}{agent}" not in {g.name for g in await self.offers_in(caller, parent_thread_id)}:
            message = "That agent cannot be asked on this turn."
            return ToolOutcome(ok=False, output={"error": message, "code": "specialist_not_offered"})
        assert callee is not None, "offered above"
        started_for = chain.started_for
        path: list[JsonValue] = [*chain.path]
        base: Json = {"agent": callee.id, "agentName": callee.name, "path": path}
        meta: Json = {
            "calledBy": caller,
            "calledByName": parent_meta.get("agentName"),
            "agentId": callee.id,
            "agentName": callee.name,
            "agentVersion": callee.version,
            "startedFor": started_for,
            "parentThreadId": parent_thread_id,
            "parentRunId": parent_run_id,
            # Kept on the thread, so a turn resumed after an approval is on the same chain.
            "chain": chain.wire(),
        }
        row, created = await store.open_thread(
            new_id("th"),
            CHAT_GRAPH,
            meta,
            parent.team_id,
            now_iso(),
            external_key=f"tool:{key}",
            parent_thread_id=parent_thread_id,
        )
        thread_id = row.id
        if created:
            graph_input: Json = {
                "agent_id": callee.id,
                "message": str(arguments.get("question") or ""),
                "history": [],
                # Who an approval's card names as the asker; a run with no person has none to name.
                "requested_by": started_for if person is not None else "",
            }
            run_id = "run_" + hashlib.sha256(key.encode()).hexdigest()[:16]
            await run_child(self.rt, thread_id, graph_input, run_id=run_id)
        _, graph = await resolve(self.rt, thread_id)
        snap = await graph.aget_state(config(thread_id))
        base = base | {"threadId": thread_id}
        if pending(snap):
            return ToolOutcome(ok=True, output=base | {"status": "waiting_review"})
        runs = await store.runs(thread_id)
        if runs and runs[-1].status == "error":
            return ToolOutcome(ok=False, output=base | {"status": "failed"})
        values = narrow.an_object(snap.values or {}, "the specialist's values")
        if values.get("stop") == "budget_reached":
            # The specialist's reply ended at the budget its chain shares: the asking agent reads what it had written
            # and answers from that.
            return ToolOutcome(ok=False, output=base | BUDGET_REACHED | {"answer": values.get("reply")})
        return ToolOutcome(ok=True, output=base | {"status": "answered", "answer": values.get("reply")})
