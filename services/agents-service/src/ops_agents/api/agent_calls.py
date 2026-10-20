"""Specialist agents as tools (c-174): the team's default agent asks another agent by calling `agent__<id>`, and that
agent answers with its own turn: its knowledge, tools, guardrails and approvals, for the same person.

Who may be asked is decided per turn: only the team's default agent is offered specialists, only those the turn's person
may chat with (chat.run on the specialist's team), and never on a specialist's own turn, so a specialist cannot ask
another (depth 1). A turn with no person (an unattended run, or a turn resumed after a decision) asks no one.
"""

from __future__ import annotations

import hashlib
from typing import Any, cast

from langgraph.config import get_config

from ops_access import can
from ops_agent_kernel.ports import ToolOutcome
from ops_agent_kernel.types import ToolGrant
from ops_service_kit.errors import Forbidden
from ops_service_kit.ids import new_id, now_iso

from ..graphs.common import AGENT_TOOL_PREFIX
from ..store.team_defaults import TeamDefaults
from .agent_registry import registry
from .auth import caller_of
from .chat_threads import CHAT_GRAPH
from .child_runs import TURN_PERSON, run_child
from .deps import Runtime
from .runs import config, graph_store, pending, resolve

QUESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"question": {"type": "string", "description": "The whole question, with what the person said"}},
    "required": ["question"],
}


async def agent_team(rt: Runtime, agent_id: str) -> str | None:
    """The team that owns an agent; None for an agent with no registry row or no team, which every team may use."""
    return await registry(rt).owner_team(agent_id)


class AgentCalls:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    async def offers(self, agent_id: str) -> list[ToolGrant]:
        try:
            thread_id = str((get_config().get("configurable") or {}).get("thread_id") or "")
        except RuntimeError:
            return []  # not inside a graph run, so there is no turn to offer specialists to
        return await self.offers_in(agent_id, thread_id)

    async def offers_in(self, agent_id: str, thread_id: str) -> list[ToolGrant]:
        """The specialists `agent_id` may ask on a turn of `thread_id`, for the turn's person."""
        person = TURN_PERSON.get()
        if person is None:
            return []
        thread = await graph_store(self.rt).thread(thread_id) if thread_id else None
        if thread is None or cast(dict[str, Any], thread["meta"] or {}).get("calledBy"):
            return []  # a specialist's own turn asks no one
        if await TeamDefaults(self.rt.db).agent(str(thread["team_id"])) != agent_id:
            return []
        out: list[ToolGrant] = []
        for a in self.rt.catalog.agents:
            if a.id == agent_id:
                continue
            if team := await agent_team(self.rt, a.id):
                try:
                    can(caller_of(person), "chat", "run", team=team, what=a.name)
                except Forbidden:
                    continue  # the person may not chat with it, so the default agent may not ask it for them
            out.append(
                ToolGrant(
                    name=f"{AGENT_TOOL_PREFIX}{a.id}",
                    server="agents",
                    description=f"Ask {a.name}, the {a.role}. It answers from its own knowledge and tools.",
                    # Asking changes nothing; the specialist's own write tools still wait for approval in its turn.
                    access="read",
                    input_schema=QUESTION_SCHEMA,
                )
            )
        return out

    async def run(
        self, *, agent: str, arguments: dict[str, Any], key: str, parent_thread_id: str, parent_run_id: str | None
    ) -> ToolOutcome:
        store = graph_store(self.rt)
        parent = await store.thread(parent_thread_id)
        assert parent is not None, "a tool runs inside its parent's run"
        parent_meta = cast(dict[str, Any], parent["meta"] or {})
        caller = str(parent_meta.get("agentId") or "")
        # Checked again here, not only when offered: a model may name a tool it was never given.
        if f"{AGENT_TOOL_PREFIX}{agent}" not in {g.name for g in await self.offers_in(caller, parent_thread_id)}:
            message = "That agent cannot be asked on this turn."
            return ToolOutcome(ok=False, output={"error": message, "code": "specialist_not_offered"})
        person = TURN_PERSON.get()
        callee = self.rt.catalog.agent(agent)
        assert person is not None and callee is not None, "offered above"
        meta = {
            "calledBy": caller,
            "calledByName": parent_meta.get("agentName"),
            "agentId": callee.id,
            "agentName": callee.name,
            "agentVersion": callee.version,
            "startedFor": person.email,
            "parentThreadId": parent_thread_id,
            "parentRunId": parent_run_id,
        }
        row, created = await store.find_or_create_thread(
            new_id("th"),
            CHAT_GRAPH,
            meta,
            parent["team_id"],
            now_iso(),
            external_key=f"tool:{key}",
            parent_thread_id=parent_thread_id,
        )
        thread_id = row["id"]
        if created:
            graph_input: dict[str, Any] = {
                "agent_id": callee.id,
                "message": str(arguments.get("question") or ""),
                "history": [],
                "requested_by": person.email,
            }
            run_id = "run_" + hashlib.sha256(key.encode()).hexdigest()[:16]
            await run_child(self.rt, thread_id, graph_input, run_id=run_id)
        _, graph = await resolve(self.rt, thread_id)
        snap = await graph.aget_state(config(thread_id))
        base = {"agent": callee.id, "agentName": callee.name, "threadId": thread_id}
        if pending(snap):
            return ToolOutcome(ok=True, output=base | {"status": "waiting_review"})
        runs = await store.runs(thread_id)
        if runs and runs[-1]["status"] == "error":
            return ToolOutcome(ok=False, output=base | {"status": "failed"})
        values = cast(dict[str, Any], snap.values or {})
        return ToolOutcome(ok=True, output=base | {"status": "answered", "answer": values.get("reply")})
