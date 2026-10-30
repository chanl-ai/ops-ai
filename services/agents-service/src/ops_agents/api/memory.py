"""What an agent remembers about each person (c-124, c-557), on the chat path.

Write: beside each chat turn, one schema-bound model call reads the last messages with the person's words marked and
the person's closest saved memories, and lists candidates, each with a kind, a quote, a confidence and a decision
against what is already kept. Only a quote from the person's own words is saved, never a tool result or the agent's
reply, so a prompt injection in a tool's output cannot write memory. A sure candidate is used at once, an unsure one
waits as a suggestion, a guess is dropped. A memory is kept for every agent in the person's team.

Read: the person's current facts and preferences go into the turn as one instruction fragment after the agent's own
prompt, and `search_memory` finds the rest. Every read and write is scoped by the person (their token's subject) and
the team; a turn with no person (an unattended run) remembers nothing.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Protocol, cast

from langgraph.config import get_config

from ops_agent_kernel.aliases import PreferredAlias
from ops_agent_kernel.ports import ToolOutcome
from ops_agent_kernel.types import PromptFragment, ToolGrant
from ops_contracts.chat import ChatMessage, RememberedItem
from ops_service_kit.logging import get_logger

from ..activities.catalog import AgentDefinition
from ..graphs.common import MEMORY_TOOL
from ..store.events import EventLog
from ..store.memories import ACTIVE, ASKED_FOR, CONFLICT, EVERY_AGENT, FORGOTTEN, SUGGESTED, Memories
from .auth import Principal
from .child_runs import TURN_PERSON
from .deps import Runtime
from .engine_agents import KernelModels
from .memory_safety import sensitive
from .runs import graph_store

log = get_logger("ops_agents.memory")

# Below this a candidate is a guess and is dropped (owner idea 4: low confidence is held back).
MIN_CONFIDENCE = 0.5
# From here a candidate is saved and used at once; between the two it waits as a suggestion for the person's yes.
SURE = 0.8
# A turn shorter than this says too little to learn from, and is not worth a model call.
MIN_TURN_CHARS = 20
# The messages learning reads: the person's message and the five before it.
WINDOW = 6
# The closest saved memories the extraction is shown, so it can tell a new memory from one already kept.
CANDIDATES = 10
# Words of the person's that find those memories.
MATCH_WORDS = 12
# How long a finished reply waits for its extraction before it ends without one.
EXTRACTION_DEADLINE_SECONDS = 10.0
# "Remember that ..." is saved as said up to this length; anything longer is pasted content, not a thing to remember.
REMEMBER_MAX = 300
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_REMEMBER = re.compile(r"^\s*remember(?: that)?\s*[:,]?\s+(.+?)\s*$", re.I | re.S)
_WORD = re.compile(r"[a-z0-9][a-z0-9'-]{3,}")
_FENCED = re.compile(r"```.*?(```|$)", re.S)
_REPORTED = re.compile(r"\b(?:wrote|writes|says|said)\s*:", re.I)
_QUOTED = re.compile(r"\"[^\"]*\"|\u201c[^\u201d]*\u201d")
_COMMON = frozenset(
    {"that", "this", "with", "from", "have", "what", "your", "about", "would", "could", "please", "thanks"}
)
# Recall: at most PINNED standing preferences and ways of working go into every turn, whatever the question.
PINNED = 5
PINNED_KINDS = ("preference", "procedure")
# The most memories, and prompt tokens of them, one turn is given; the rest are found with search_memory.
RECALL_MEMORIES = 8
RECALL_TOKENS = 600
# A prompt line costs its characters / CHARS_PER_TOKEN, rounded up, so the budget is the same on every model.
CHARS_PER_TOKEN = 4
# A memory unused for RECENCY_DAYS weighs RECENCY_FLOOR of a fresh one, and never less.
RECENCY_DAYS = 180
RECENCY_FLOOR = 0.5
KIND_BOOST = 1.2
# The most memories recall ranks: the database's best matches for the question, and its standing preferences.
POOL = 50
SEARCH_RESULTS = 10
KINDS = ("preference", "procedure", "fact", "person", "case", "episode")
# What one turn may teach: something about the person or how they work. An episode (what they asked once) and a case
# (a matter they handle) describe the conversation, not the person, and case facts stay on the case.
LEARNED_KINDS = ("preference", "procedure", "fact", "person")
# An agent's memory switches name three kinds; each newer kind follows the switch of the kind it refines.
KIND_SWITCH = {"procedure": "preference", "person": "fact", "case": "fact"}
DECISIONS = ("new", "same", "replaces", "conflicts")
# Marks a candidate the person asked to be remembered ("remember that ..."): saved as theirs, confirmed.
ASKED = "_asked"
SENSITIVITIES = ("none", "personal", "restricted")
# Never kept, whatever the model's confidence: health, finances, credentials and identity numbers.
NEVER_KEPT = "restricted"

EXTRACT_SYSTEM = (
    "You read the end of a conversation between a person and an assistant and list what is worth remembering about "
    "the person for later conversations. Lines starting 'person:' are the person's words; only they can be "
    "remembered, never the assistant's lines nor text they pasted or quoted from someone else. Kinds: preference (how "
    "they want help), procedure (a way of working they follow), fact (about them or their work), person (someone they "
    "work with, by role); never what they asked for once. For each give a short key naming the "
    "subject, a one-sentence value, the quote (their exact words it comes from), a confidence from 0 to 1, and a "
    "sensitivity: restricted for health, finances, credentials or identity numbers, personal for other private "
    "details, else none. Memories already kept are listed under <saved> with their ids: answer same and its id when "
    "the person repeats one, replaces and its id when they change one (a new preference about the same thing, in "
    "other words, changes it), conflicts and its id when they contradict one, "
    "otherwise new. No secrets, passwords or card numbers. Return an empty list when there is nothing to remember."
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
                    "kind": {"enum": list(LEARNED_KINDS)},
                    "key": {"type": "string", "maxLength": 120},
                    "value": {"type": "string", "minLength": 1, "maxLength": 500},
                    "quote": {"type": "string", "minLength": 1, "maxLength": 500},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "sensitivity": {"enum": list(SENSITIVITIES)},
                    "decision": {"enum": list(DECISIONS)},
                    "ref": {"type": "string", "maxLength": 64},
                },
                "required": ["kind", "value", "quote", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["memories"],
    "additionalProperties": False,
}


class Extractor(Protocol):
    async def structured(self, system: str, user: str, schema: dict[str, Any], *, key: str) -> Any: ...


class MemoryMatcher(Protocol):
    """Finds the person's saved memories closest to what they said: the database's full-text search today
    (store/memories.py); a matcher by meaning goes behind the same call once models-service serves embeddings."""

    async def matches(
        self, person: str, team_id: str, agent_id: str, words: list[str], *, limit: int = 10
    ) -> list[dict[str, Any]]: ...


def person_of(me: Principal) -> str:
    """The id memories are keyed by: the token's subject. The dev header caller carries the one dev user's subject
    whoever it names, so it is keyed by the email it names instead, or every dev person would share memories."""
    return me.email if me.dev else (me.sub or me.email)


def _key(raw: Any) -> str | None:
    """A memory's key as lowercase words: the model may write summaryFormatPreference or answer_style, and the key is
    shown to the person and matched against later saves."""
    text = " ".join(_CAMEL.sub(" ", str(raw or "")).replace("_", " ").split()).lower()
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


@dataclass(frozen=True)
class Extraction:
    """What one turn's extraction found, with what saving it needs: the ids of the saved memories it was shown (a
    decision about any other id is not trusted), the person's own words in their latest message (every quote must come
    from them), and the text of a "remember that" message."""

    found: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    offered: frozenset[str] = frozenset()
    theirs: str = ""
    remember: str | None = None


def _plain(text: Any) -> str:
    return " ".join(str(text or "").lower().split())


def _own_words(message: str) -> str:
    """The person's own words in their latest message, plain: without fenced blocks, lines quoted with `>`, text in
    double quotes and the rest of a line after "wrote:", "says:" or "said:", which carry what someone else wrote (a
    pasted email) rather than what they say about themselves."""
    text = _FENCED.sub(" ", message)
    lines = [_REPORTED.split(line)[0] for line in text.splitlines() if not line.lstrip().startswith(">")]
    return _plain(_QUOTED.sub(" ", "\n".join(lines)))


def _window(history: Sequence[Any], message: str) -> list[tuple[str, str]]:
    """The last WINDOW messages as (who, text), the person's message last; who is person or assistant."""
    lines = [("person" if m.role == "user" else "assistant", str(m.content)) for m in history if m.content]
    return [*lines[-(WINDOW - 1) :], ("person", message)]


def _says_the_same(saved: str, said: str) -> bool:
    """Whether a value says what a saved one says: every word of one in the other, ignoring short and common words;
    values made only of those must be equal."""
    a, b = (set(_WORD.findall(_plain(v))) - _COMMON for v in (saved, said))
    return a <= b or b <= a if a and b else _plain(saved) == _plain(said)


def _words(theirs: str) -> list[str]:
    return list(dict.fromkeys(w for w in _WORD.findall(theirs) if w not in _COMMON))[:MATCH_WORDS]


async def extract_memories(
    extractor: Extractor,
    agent: AgentDefinition,
    *,
    thread_id: str,
    message: str,
    history: Sequence[Any] = (),
    offered: Sequence[dict[str, Any]] = (),
) -> Extraction:
    """What the conversation's end says about the person, as the extractor reads it: the model call alone, which needs
    only the messages so far, so a chat turn starts it beside the reply. A failed extraction finds nothing and never
    fails the turn; a turn too short to say anything is not read."""
    if not agent.memory_enabled or len(message.strip()) < MIN_TURN_CHARS:
        return Extraction()
    lines = _window(history, message)
    theirs = _own_words(message)
    said = _REMEMBER.match(message)
    remember = said[1] if said and len(said[1]) <= REMEMBER_MAX else None
    marked = "\n".join(f"{who}: {' '.join(text.split())[:1000]}" for who, text in lines)
    saved = "\n".join(f"[{r['id']}] {r['kind']} {r['key'] or ''}: {r['value']}" for r in offered)
    prompt = f"<remember>\n{marked}\n</remember>" + (f"\n<saved>\n{saved}\n</saved>" if saved else "")
    ids = frozenset(str(r["id"]) for r in offered)
    try:
        answer = await extractor.structured(EXTRACT_SYSTEM, prompt, SCHEMA, key=f"memory:{thread_id}")
    except Exception as e:
        log.warning("memory extraction failed", extra={"thread": thread_id, "error": str(e)})
        return Extraction(offered=ids, theirs=theirs, remember=remember)
    found = cast(dict[str, Any], answer).get("memories") if isinstance(answer, dict) else None
    return Extraction(list(cast(list[dict[str, Any]], found or [])), ids, theirs, remember)


async def start_learning(
    rt: Runtime,
    me: Principal,
    agent: AgentDefinition,
    *,
    team_id: str,
    thread_id: str,
    message: str,
    history: Sequence[Any] = (),
) -> Extraction:
    """A chat turn's learning up to the model's answer: the person's closest saved memories, then the extraction."""
    if not agent.memory_enabled or len(message.strip()) < MIN_TURN_CHARS:
        return Extraction()
    theirs = " ".join(_plain(text) for who, text in _window(history, message) if who == "person")
    matcher: MemoryMatcher = Memories(graph_store(rt).engine)
    offered = await matcher.matches(person_of(me), team_id, agent.id, _words(theirs), limit=CANDIDATES)
    return await extract_memories(
        extractor_for(rt), agent, thread_id=thread_id, message=message, history=history, offered=offered
    )


async def finish_learning(
    rt: Runtime,
    me: Principal,
    agent: AgentDefinition,
    learning: asyncio.Future[Extraction],
    *,
    team_id: str,
    thread_id: str,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Saves what the turn's learning found once the reply is written. A reply waits for it at most
    EXTRACTION_DEADLINE_SECONDS: past that the turn ends and nothing is saved."""
    try:
        found = await asyncio.wait_for(learning, EXTRACTION_DEADLINE_SECONDS)
    except TimeoutError:
        log.warning("memory extraction timed out", extra={"thread": thread_id})
        return []
    return await save_memories(rt, me, agent, found, team_id=team_id, thread_id=thread_id, run_id=run_id)


def _tokens(line: str) -> int:
    return -(-len(line) // CHARS_PER_TOKEN)


def _recency(row: dict[str, Any], now: datetime) -> float:
    at = datetime.fromisoformat(str(row["last_used_at"] or row["created_at"]))
    return max(RECENCY_FLOOR, 1 - (now - at).total_seconds() / 86400 / RECENCY_DAYS)


def _kept_kind(agent: AgentDefinition, kind: str) -> bool:
    return kind in LEARNED_KINDS and KIND_SWITCH.get(kind, kind) in agent.memory_kinds


def keepable(agent: AgentDefinition, extraction: Extraction) -> list[dict[str, Any]]:
    """What may be saved from an extraction, each with kind, key, value, quote, confidence, sensitivity, decision, ref
    and whether the person asked for it: a kind one turn may teach and the agent keeps, sure enough, not restricted,
    holding no card number, IBAN or national id (memory_safety.py),
    quoted verbatim from the person's own words in their latest message, and one per memory: a candidate naming a
    memory it was shown wins over a new one for the same key, then the first."""
    found = [dict(m) for m in extraction.found]
    if extraction.remember is not None:
        # "Remember that ..." needs no judgement: the model's reading of it is kept for its kind and key, else as said.
        # The model may quote the asking words too, so a quote counts when either holds the other.
        asked = _plain(extraction.remember)
        meant = [m for m in found if (q := _plain(m.get("quote"))) and (q in asked or asked in q)]
        for m in meant:
            m |= {"confidence": 1.0, ASKED: True}
        if not meant:
            said = extraction.remember
            found.append({"kind": "fact", "key": said, "value": said, "quote": said, "confidence": 1.0, ASKED: True})
    out: list[dict[str, Any]] = []
    for m in found:
        kind, confidence, quote = str(m.get("kind")), float(m.get("confidence") or 0), _plain(m.get("quote"))
        if not _kept_kind(agent, kind) or confidence < MIN_CONFIDENCE or m.get("sensitivity") == NEVER_KEPT:
            continue
        # A card number, IBAN or national id is never kept, however the model marked it.
        if sensitive(f"{m.get('value')} {m.get('quote')} {m.get('key')}"):
            continue
        # Only the person's own words become a memory: a quote from a reply, a tool, a paste or nowhere is dropped.
        if not quote or quote not in extraction.theirs or (key := _key(m.get("key"))) is None:
            continue
        decision, ref = str(m.get("decision") or "new"), str(m.get("ref") or "")
        if ref not in extraction.offered:
            # The model may refer only to a memory it was shown; any other id is not acted on.
            decision, ref = "new", ""
        sensitivity = str(m.get("sensitivity") or "none")
        out.append(
            {
                "kind": kind,
                "key": key,
                "value": str(m["value"]).strip()[:2000],
                "quote": str(m.get("quote"))[:500],
                "confidence": confidence,
                "sensitivity": sensitivity if sensitivity in SENSITIVITIES else "none",
                "decision": decision,
                "ref": ref,
                ASKED: bool(m.get(ASKED)),
            }
        )
    # One decision per memory a turn touches: grouped by the memory named, else by key.
    first: dict[str, dict[str, Any]] = {}
    for m in sorted(out, key=lambda m: not m["ref"]):
        first.setdefault(m["ref"] or f"key:{m['key']}", m)
        if m["ref"]:
            first.setdefault(f"key:{m['key']}", m)
    chosen = {id(m) for m in first.values()}
    return [m for m in out if id(m) in chosen]


async def save_memories(
    rt: Runtime,
    me: Principal,
    agent: AgentDefinition,
    extraction: Extraction,
    *,
    team_id: str,
    thread_id: str,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    """Saves what the agent keeps of the extraction, for every agent in the team: sure memories in use at once, unsure
    ones as suggestions; the saved ones, also written to the thread's log as a `memory` event on the turn's run so its
    reply says what was kept, live and after a reload."""
    store = Memories(graph_store(rt).engine)
    person = person_of(me)
    saved: list[dict[str, Any]] = []
    for m in keepable(agent, extraction):
        kind, key, value, ref = m["kind"], m["key"], m["value"], m["ref"]
        # A change the person makes in their own words ("change that to ...") replaces the memory, even one they
        # confirmed; only the model's "conflicts", a contradiction they did not ask for, waits.
        changed = m["decision"] == "replaces"
        if m["decision"] == "same":
            kept = await store.get(person, ref)
            if kept is not None and _says_the_same(str(kept["value"]), value):
                await store.confirm(person, team_id, ref)
                saved.append(
                    {"id": ref, "kind": kind, "key": key, "value": kept["value"], "status": ACTIVE, "decision": "same"}
                )
                continue
            # The model named a saved memory as the same, but the value differs: the person changed it.
            changed = True
        row = await store.save(
            team_id=team_id,
            agent_id=EVERY_AGENT,
            person=person,
            kind=kind,
            key=key,
            value=value,
            confidence=m["confidence"],
            source=ASKED_FOR if m[ASKED] else "extraction",
            thread_id=thread_id,
            status=ACTIVE if m["confidence"] >= SURE else SUGGESTED,
            quote=m["quote"],
            sensitivity=m["sensitivity"],
            supersedes_id=ref or None,
            confirmed=m[ASKED] or changed,
        )
        decided = "conflicts" if row["status"] == CONFLICT else "replaces" if row["supersedes_id"] else "new"
        saved.append(
            {"id": row["id"], "kind": kind, "key": key, "value": value, "status": row["status"], "decision": decided}
        )
    if saved:
        # The thread keeps ids only, so erasing a memory leaves none of its text in the conversation.
        logged = [{k: s[k] for k in ("id", "kind", "status", "decision")} for s in saved]
        await EventLog(graph_store(rt).engine).append(
            thread_id=thread_id, team_id=team_id, run_id=run_id, type_="memory", data={"saved": logged}
        )
    return saved


async def fill_remembered(rt: Runtime, messages: Sequence[ChatMessage], reader: str | None = None) -> None:
    """Gives each reply's remembered items the memory's status now, read from the memories (the thread holds ids
    only), and its key and value only when `reader` is the memory's person: anyone else allowed to read the thread
    sees that something was remembered, never what. A memory forgotten or erased since shows as forgotten."""
    items = [r for msg in messages for r in msg.remembered or []]
    rows = await Memories(graph_store(rt).engine).by_ids([r.id for r in items])
    for msg in messages:
        if not msg.remembered:
            continue
        shown: list[RememberedItem] = []
        for r in msg.remembered:
            row = rows.get(r.id)
            if row is None or row["status"] == FORGOTTEN:
                shown.append(r.model_copy(update={"key": None, "value": None, "status": FORGOTTEN}))
            elif reader is not None and row["person"] == reader:
                shown.append(r.model_copy(update={"key": row["key"], "value": row["value"], "status": row["status"]}))
            else:
                shown.append(r.model_copy(update={"key": None, "value": None, "status": row["status"]}))
        msg.remembered = shown


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
        """The turn's recall, inside the agent's graph: the person, team, question and reply come from the run."""
        person = TURN_PERSON.get()
        if person is None:
            return None
        configurable = get_config().get("configurable") or {}
        thread_id, run_id = str(configurable.get("thread_id") or ""), str(configurable.get("run_id") or "")
        store = graph_store(self.rt)
        thread = await store.thread(thread_id) if thread_id else None
        run = await store.run(run_id) if run_id else None
        if thread is None or run is None:
            return None
        given = cast(dict[str, Any], cast(dict[str, Any], run.get("input") or {}).get("input") or {})
        # chat_threads reads this module to fill a reply's remembered items, so this import waits until a turn runs.
        from .chat_threads import assistant_id  # noqa: PLC0415

        return await self.recall(
            person_of(person),
            str(thread["team_id"]),
            agent_id,
            str(given.get("message") or ""),
            thread_id=thread_id,
            message_id=assistant_id(run_id),
        )

    async def recall(
        self,
        person: str,
        team_id: str,
        agent_id: str,
        question: str,
        *,
        thread_id: str | None = None,
        message_id: str | None = None,
    ) -> PromptFragment | None:
        """What the person's memories in this team give a turn on `question`: up to PINNED standing preferences and
        ways of working, then the database's best full-text matches for the question, ranked again by their match
        times confidence times recency, with a boost for preferences and procedures, until RECALL_MEMORIES memories or
        RECALL_TOKENS tokens. Each line carries the memory's id; with `message_id` the ids used and why are recorded
        for that reply and their use counted."""
        if self._agent(agent_id) is None:
            return None
        store = Memories(graph_store(self.rt).engine)
        standing = await store.in_use(person, team_id, agent_id, kinds=PINNED_KINDS, limit=POOL)
        pinned = sorted(standing, key=lambda r: str(r["confirmed_at"] or r["created_at"]), reverse=True)[:PINNED]
        found = await store.matches(person, team_id, agent_id, _words(_plain(question)), limit=POOL)
        best, now = max((float(r["match"]) for r in found), default=0.0), datetime.now(UTC)

        def score(r: dict[str, Any]) -> float:
            boost = KIND_BOOST if r["kind"] in PINNED_KINDS else 1.0
            return float(r["match"]) / best * float(r["confidence"]) * _recency(r, now) * boost

        chosen = {r["id"] for r in pinned}
        matched = sorted((r for r in found if r["id"] not in chosen), key=score, reverse=True)
        picks: list[tuple[str, str]] = []
        lines: list[str] = []
        spent = 0
        for r, reason in [*((r, "pinned") for r in pinned), *((r, "matched") for r in matched)]:
            line = f"- [{r['id']}] {r['key']}: {r['value']}" if r["key"] else f"- [{r['id']}] {r['value']}"
            if len(picks) == RECALL_MEMORIES or spent + _tokens(line) > RECALL_TOKENS:
                break
            picks.append((str(r["id"]), reason))
            lines.append(line)
            spent += _tokens(line)
        if not picks:
            return None
        if message_id and thread_id:
            await store.record_use(team_id, thread_id, message_id, picks)
        # Not stable: it changes per person, so it sits after the agent's own prompt, which the prefix cache keeps.
        return PromptFragment(
            "What you remember about the person you are talking to, from earlier conversations. Use it when it helps, "
            "and believe what they say now over it. They can see and delete what you remember.\n" + "\n".join(lines),
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
        words = [w.lower() for w in str(arguments.get("query") or "").split() if len(w) > 2][:6]
        rows = await Memories(graph_store(self.rt).engine).matches(
            person_of(person), str((thread or {}).get("team_id") or ""), agent_id, words, limit=SEARCH_RESULTS
        )
        return ToolOutcome(
            ok=True, output={"memories": [{"kind": r["kind"], "key": r["key"], "value": r["value"]} for r in rows]}
        )
