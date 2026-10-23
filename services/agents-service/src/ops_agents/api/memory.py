"""What an agent remembers about each person (c-124), on the chat path.

Write: after a chat turn, one schema-bound model call reads the person's own message, never a tool result or the
agent's reply, so a prompt injection in a tool's output cannot write memory. Each candidate is a fact, preference or
episode with a confidence; below MIN_CONFIDENCE it is not saved, a kind the agent switched off is not saved, and a fact
or preference supersedes the current one with the same key.

Read: the person's current facts and preferences go into the turn as one instruction fragment after the agent's own
prompt, and `search_memory` finds the rest. Every read and write is scoped by the person (their token's subject) and
the agent; a turn with no person (an unattended run) remembers nothing.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Protocol, cast

from langgraph.config import get_config

from ops_agent_kernel.aliases import PreferredAlias
from ops_agent_kernel.ports import ToolOutcome
from ops_agent_kernel.types import PromptFragment, ToolGrant
from ops_service_kit.logging import get_logger

from ..activities.catalog import AgentDefinition
from ..graphs.common import MEMORY_TOOL
from ..store.events import EventLog
from ..store.memories import Memories
from .auth import Principal
from .child_runs import TURN_PERSON
from .deps import Runtime
from .engine_agents import KernelModels
from .runs import graph_store

log = get_logger("ops_agents.memory")

# Below this an extraction is a guess, so it is not saved (owner idea 4: low confidence is held back).
MIN_CONFIDENCE = 0.6
# How many facts and preferences go into every turn; the rest are found with search_memory.
PROFILE_SIZE = 20

EXTRACT_SYSTEM = (
    "You read one message a person sent to an assistant and list what is worth remembering about that person for later "
    "conversations: facts about them (key and value, e.g. timezone: Eastern), preferences about how they want help "
    "(key and value), and at most one episode (a one-line summary of what they asked for, no key). Only what the "
    "person says about themselves; nothing about other people, no secrets, passwords or card numbers. Give each a "
    "confidence "
    "from 0 to 1. Return an empty list when there is nothing to remember."
)

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "memories": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"enum": ["fact", "preference", "episode"]},
                    "key": {"type": "string", "maxLength": 120},
                    "value": {"type": "string", "minLength": 1, "maxLength": 500},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["kind", "value", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["memories"],
    "additionalProperties": False,
}


class Extractor(Protocol):
    async def structured(self, system: str, user: str, schema: dict[str, Any], *, key: str) -> Any: ...


def person_of(me: Principal) -> str:
    """The id memories are keyed by: the token's subject. The dev header caller carries the one dev user's subject
    whoever it names, so it is keyed by the email it names instead, or every dev person would share memories."""
    return me.email if me.dev else (me.sub or me.email)


def _key(raw: Any) -> str | None:
    text = str(raw or "").strip().lower()
    return text[:120] or None


# The alias memory extraction runs on through models-service, so it can be faster than the agents' turns (a reply's
# end waits on it when the turn is quicker); the runtime's alias while it is not bound.
MEMORY_ALIAS = "memory-extract"


def extractor_for(rt: Runtime) -> Extractor:
    """The extractor a chat turn reads memories with: a test's, else a kernel turn on MEMORY_ALIAS."""
    if rt.memory_extractor is not None:
        return cast(Extractor, rt.memory_extractor)
    assert rt.ports is not None, "a chat turn runs only with a model configured"
    ports = rt.ports
    if ports.models is not None:
        ports = replace(ports, models=PreferredAlias(ports.models, MEMORY_ALIAS))
    return KernelModels(ports, rt.settings.model_alias)


async def extract_memories(extractor: Extractor, agent: AgentDefinition, *, thread_id: str, message: str) -> list[Any]:
    """What the person's message says about them, as the extractor reads it: the model call alone, which needs only the
    message, so a chat turn starts it beside the reply. A failed extraction finds nothing and never fails the turn."""
    if not agent.memory_enabled or not message.strip():
        return []
    try:
        answer = await extractor.structured(
            EXTRACT_SYSTEM, f"<remember>\n{message}\n</remember>", SCHEMA, key=f"memory:{thread_id}"
        )
    except Exception as e:
        log.warning("memory extraction failed", extra={"thread": thread_id, "error": str(e)})
        return []
    if not isinstance(answer, dict):
        return []
    return cast(list[Any], cast(dict[str, Any], answer).get("memories") or [])


async def save_memories(
    rt: Runtime,
    me: Principal,
    agent: AgentDefinition,
    found: list[Any],
    *,
    team_id: str,
    thread_id: str,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Saves the extracted memories the agent keeps; the saved ones, also written to the thread's log as a `memory`
    event on the turn's run so its reply says what was kept, live and after a reload."""
    store = Memories(graph_store(rt).engine)
    saved: list[dict[str, Any]] = []
    for m in cast(list[dict[str, Any]], found):
        kind = str(m.get("kind"))
        if kind not in agent.memory_kinds or float(m.get("confidence") or 0) < MIN_CONFIDENCE:
            continue
        key = None if kind == "episode" else _key(m.get("key"))
        if kind != "episode" and key is None:
            continue
        row = await store.save(
            team_id=team_id,
            agent_id=agent.id,
            person=person_of(me),
            kind=kind,
            key=key,
            value=str(m["value"]).strip()[:2000],
            confidence=float(m["confidence"]),
            source="extraction",
            thread_id=thread_id,
        )
        saved.append({"id": row["id"], "kind": kind, "key": key, "value": row["value"]})
    if saved:
        await EventLog(graph_store(rt).engine).append(
            thread_id=thread_id, team_id=team_id, run_id=run_id, type_="memory", data={"saved": saved}
        )
    return saved


async def remember_turn(
    rt: Runtime,
    extractor: Extractor,
    me: Principal,
    agent: AgentDefinition,
    *,
    team_id: str,
    thread_id: str,
    message: str,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Extracts and saves in one step (extract_memories, then save_memories)."""
    found = await extract_memories(extractor, agent, thread_id=thread_id, message=message)
    return await save_memories(rt, me, agent, found, team_id=team_id, thread_id=thread_id, run_id=run_id)


class MemoryReads:
    """The read side for an agent turn (graphs.common.MemoryRunner): the person's profile as a fragment, and the
    `search_memory` tool, both for the turn's person only."""

    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    def _agent(self, agent_id: str) -> AgentDefinition | None:
        a = self.rt.catalog.agent_in_flight(agent_id) or self.rt.catalog.agent(agent_id)
        return a if a is not None and a.memory_enabled else None

    async def profile(self, agent_id: str) -> PromptFragment | None:
        person = TURN_PERSON.get()
        if person is None or self._agent(agent_id) is None:
            return None
        rows = [
            r
            for r in await Memories(graph_store(self.rt).engine).current(person_of(person), agent_id)
            if r["kind"] in ("fact", "preference")
        ][:PROFILE_SIZE]
        if not rows:
            return None
        lines = "\n".join(f"- {r['key']}: {r['value']}" for r in rows)
        # Not stable: it changes per person, so it sits after the agent's own prompt, which the prefix cache keeps.
        return PromptFragment(
            "What you remember about the person you are talking to, from earlier conversations. Use it when it helps, "
            "and believe what they say now over it. They can see and delete what you remember.\n" + lines,
            False,
        )

    async def offers(self, agent_id: str) -> list[ToolGrant]:
        if TURN_PERSON.get() is None or self._agent(agent_id) is None:
            return []
        return [
            ToolGrant(
                MEMORY_TOOL,
                "memory",
                "Search what you remember about the person you are talking to from earlier conversations: facts, "
                "preferences and what they asked for before.",
                "read",
                {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            )
        ]

    async def run(self, arguments: dict[str, Any]) -> ToolOutcome:
        person = TURN_PERSON.get()
        thread_id = str((get_config().get("configurable") or {}).get("thread_id") or "")
        thread = await graph_store(self.rt).thread(thread_id) if thread_id else None
        agent_id = str(cast(dict[str, Any], (thread or {}).get("meta") or {}).get("agentId") or "")
        if person is None or not agent_id or self._agent(agent_id) is None:
            return ToolOutcome(ok=False, output={"error": "There is no memory to search on this turn."})
        words = [w for w in str(arguments.get("query") or "").split() if len(w) > 2][:6]
        rows = await Memories(graph_store(self.rt).engine).search(person_of(person), agent_id, words)
        return ToolOutcome(
            ok=True, output={"memories": [{"kind": r["kind"], "key": r["key"], "value": r["value"]} for r in rows]}
        )
