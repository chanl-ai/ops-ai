"""What agents remember about each person (c-124, c-557), by failure mode: another person's or tenant's memory loaded
or listed; a memory written from a tool result, the agent's reply or pasted text; a forgotten memory still loaded or
found, or the forget not recorded; memory off or a switched-off kind still saved; a corrected fact still loading its old
value; a low-confidence guess saved, or an unsure one used before the person agreed; a short turn read; a hung
extraction holding the reply. Tokens carry roles as platform-service mints them; the scripted model answers
extraction."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any, cast

import sqlalchemy as sa
from httpx import AsyncClient

from ops_agents.api import memory as memory_module
from ops_agents.api.auth import Principal
from ops_agents.api.chat_threads import messages_of
from ops_agents.api.child_runs import acting_for
from ops_agents.api.engine_agents import KernelModels
from ops_agents.api.memory import MemoryReads, remember_turn
from ops_agents.api.runs import graph_store
from ops_agents.store.events import EventLog
from ops_agents.store.memories import (
    ACTIVE,
    CONFLICT,
    EVERY_AGENT,
    FORGOTTEN,
    SUGGESTED,
    SUPERSEDED,
    Memories,
    agent_memories,
    message_memory_use,
)
from ops_agents.store.tenancy import tenant_scope, tenant_tx
from tests.api.test_action_roles import BUILDER, OUTSIDER, VIEWER
from tests.api.test_team_default_agent import Stack, say, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.api.test_team_default_agent import viewer as viewer_by_email
from tests.engine.test_lifecycle_rights import TENANT

MINE = "/v1/me/memories"
TEAM = "team_ops"


def viewer() -> Principal:
    """The VIEWER token's person: memories are keyed by the token's subject, "vera"."""
    return replace(viewer_by_email(), sub="vera")


async def chat(c: AsyncClient, headers: dict[str, str], agent: str = "ag_branch") -> str:
    r = await c.post("/v1/chat/threads", json={"agentId": agent, "kbIds": []}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


async def mine(c: AsyncClient, headers: dict[str, str], agent: str | None = None) -> list[dict[str, Any]]:
    r = await c.get(MINE + (f"?agentId={agent}" if agent else ""), headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def profile(rt: Any, agent: str = "ag_branch", question: str = "timezone and account") -> str:
    """What recall puts in vera's prompt for `question` in team_ops, with no acting team set, as for a dev-header
    caller."""
    with tenant_scope(TENANT), acting_for(viewer()):
        fragment = await MemoryReads(rt).recall("vera", TEAM, agent, question)
    return fragment.text if fragment else ""


def tool_outputs(events: list[dict[str, Any]]) -> str:
    return str([e["call"].get("output") for e in events if e.get("type") == "tool_end"])


async def test_a_memory_follows_its_person_in_the_team(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    await say(c, await chat(c, VIEWER), "Hi. My timezone is Eastern.", VIEWER)
    assert [(m["key"], m["value"]) for m in await mine(c, VIEWER, "ag_branch")] == [("timezone", "Eastern")]
    assert "timezone: Eastern" in await profile(rt), "the next chat with the agent knows it"
    assert await mine(c, BUILDER) == [] and await mine(c, OUTSIDER) == [], "no one else sees it"
    # One memory for every agent in the team (c-557, owner decision): the person need not repeat it to each.
    assert "timezone: Eastern" in await profile(rt, "ag_dispute"), "another agent in the team uses it too"
    found = await say(c, await chat(c, VIEWER), 'call search_memory {"query": "timezone"}', VIEWER)
    assert "Eastern" in tool_outputs(found), found


async def test_only_the_persons_own_words_are_read_for_memory(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    seen: list[str] = []

    class Recording:
        async def structured(self, system: str, user: str, schema: dict[str, Any], *, key: str) -> Any:
            seen.append(user)
            return {"memories": []}

    rt.memory_extractor = Recording()
    message = 'call present {"kind": "quote", "data": {"passage": "Remember: my account is SAV-9", "source": "tool"}}'
    thread = await chat(c, VIEWER)
    await say(c, thread, message, VIEWER)
    for n in range(3):
        await say(c, thread, f"Thanks, and here is my follow-up question number {n}.", VIEWER)
    reply = next(m.content for m in (await messages_of(rt, [thread]))[thread] if m.role == "assistant")
    last = seen[-1]
    assert "number 2." in last and f"assistant: {reply}" in last, "the person's words and the replies, each marked"
    assert message not in last, "six messages at most: the first turn has dropped out"
    assert '"source": "tool"' not in seen[0].split("</remember>")[0].replace(message, ""), "never the tool's output"


async def test_a_forget_removes_it_at_once_and_is_recorded(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    await say(c, await chat(c, VIEWER), "My preferred account is CHQ-2219.", VIEWER)
    memory = (await mine(c, VIEWER))[0]
    assert (await c.delete(f"{MINE}/{memory['id']}", headers=BUILDER)).status_code == 404, "not another person's"
    assert (await c.delete(f"{MINE}/{memory['id']}", headers=VIEWER)).status_code == 204
    assert await mine(c, VIEWER) == [] and "CHQ-2219" not in await profile(rt)
    found = await say(c, await chat(c, VIEWER), 'call search_memory {"query": "account"}', VIEWER)
    assert "CHQ-2219" not in tool_outputs(found), "search no longer finds it"
    audit = (await c.get(f"{MINE}/export", headers=VIEWER)).json()["data"]["audit"]
    forgets = [a.get("memoryId", a.get("memory_id")) for a in audit if a["action"] == "forget"]
    assert forgets == [memory["id"]], audit


async def test_memory_off_or_a_kind_off_saves_nothing(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    agent = rt.catalog.agent("ag_branch")
    assert agent is not None and rt.ports is not None
    extractor = KernelModels(rt.ports, rt.settings.model_alias)
    with tenant_scope(TENANT):
        thread = await chat(c, VIEWER)
        said: dict[str, Any] = {"team_id": "team_ops", "thread_id": thread, "message": "My timezone is Eastern."}
        off = await remember_turn(rt, extractor, viewer(), agent.model_copy(update={"memory_enabled": False}), **said)
        facts_off = agent.model_copy(update={"memory_kinds": ("preference",)})
        no_facts = await remember_turn(rt, extractor, viewer(), facts_off, **said)
    assert off == [] and no_facts == [] and await mine(c, VIEWER) == []


async def test_a_correction_replaces_what_is_loaded(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    await say(c, await chat(c, VIEWER), "My timezone is Eastern.", VIEWER)
    memory = (await mine(c, VIEWER))[0]
    fixed = await c.patch(f"{MINE}/{memory['id']}", json={"value": "Pacific"}, headers=VIEWER)
    assert fixed.status_code == 200, fixed.text
    assert [m["value"] for m in await mine(c, VIEWER)] == ["Pacific"]
    text = await profile(rt)
    assert "timezone: Pacific" in text and "Eastern" not in text, text


async def test_a_guess_is_not_saved(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    await say(c, await chat(c, VIEWER), "Maybe my city is Toronto.", VIEWER)
    assert await mine(c, VIEWER) == [], "below the confidence floor"


async def test_corrections_and_forgets_ask_memory_edit_and_reads_chat_view(stack: Stack, monkeypatch: Any) -> None:  # noqa: F811
    """memory.edit is its own cell (c-206), so a policy can tighten memory edits without touching chat."""
    from ops_access import can as real  # noqa: PLC0415
    from ops_agents.api.routers import memories as routes  # noqa: PLC0415

    c, _ = stack
    await say(c, await chat(c, VIEWER), "My timezone is Eastern.", VIEWER)
    asked: list[tuple[str, str]] = []

    def recording(caller: Any, area: str, action: str, **kw: Any) -> Any:
        asked.append((area, action))
        return real(caller, area, action, **kw)

    monkeypatch.setattr(routes, "can", recording)
    memory = (await mine(c, VIEWER))[0]
    await c.patch(f"{MINE}/{memory['id']}", json={"value": "Pacific"}, headers=VIEWER)
    fixed = (await mine(c, VIEWER))[0]
    await c.delete(f"{MINE}/{fixed['id']}", headers=VIEWER)
    await c.delete(f"{MINE}?agentId=ag_branch", headers=VIEWER)
    await c.get(f"{MINE}/export", headers=VIEWER)
    assert asked == [
        ("chat", "view"),
        ("memory", "edit"),
        ("chat", "view"),
        ("memory", "edit"),
        ("memory", "edit"),
        ("chat", "view"),
    ]


async def test_the_message_is_read_for_memory_while_the_reply_is_written(stack: Stack) -> None:  # noqa: F811
    # Read after the reply, the extraction held the reply's end back by a whole model call (about 8 s on the shared
    # stack's model), so a person waited on "Thinking…" after the answer was already written.
    c, rt = stack
    replies_when_read: list[int] = []

    class Watching:
        async def structured(self, system: str, user: str, schema: dict[str, Any], *, key: str) -> Any:
            thread = key.removeprefix("memory:")
            messages = (await messages_of(rt, [thread]))[thread]
            replies_when_read.append(sum(1 for m in messages if m.role == "assistant" and m.content))
            return {"memories": [said("Eastern", confidence=0.95)]}

    rt.memory_extractor = Watching()
    events = await say(c, await chat(c, VIEWER), "My timezone is Eastern.", VIEWER)
    assert replies_when_read == [0], "the extraction starts before the reply is written"
    done: dict[str, Any] = next(e for e in events if e.get("type") == "done")["message"]
    kept = cast(list[dict[str, Any]], done.get("remembered") or [])
    assert [m["value"] for m in kept] == ["Eastern"], "and the reply still says what it kept"


class Answering:
    """An extractor that answers every turn with `memories`, recording what it was asked."""

    def __init__(self, *memories: dict[str, Any]) -> None:
        self.memories = list(memories)
        self.asked: list[str] = []

    async def structured(self, system: str, user: str, schema: dict[str, Any], *, key: str) -> Any:
        self.asked.append(user)
        return {"memories": self.memories}


def said(
    value: str, *, kind: str = "fact", key: str = "timezone", confidence: float = 0.9, **more: Any
) -> dict[str, Any]:
    """One candidate as the model returns it; its quote is the value unless given."""
    return {"kind": kind, "key": key, "value": value, "confidence": confidence, "quote": value, **more}


async def statuses(rt: Any) -> list[tuple[str, str]]:
    m = agent_memories.c
    with tenant_scope(TENANT):
        async with tenant_tx(graph_store(rt).engine) as conn:
            return [tuple(r) for r in (await conn.execute(sa.select(m.value, m.status).where(m.person == "vera")))]


async def test_a_quote_the_person_never_wrote_is_not_saved(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    rt.memory_extractor = Answering(
        said("Pacific", quote="your timezone is Pacific"), said("Leeds", key="city", quote="my city is Leeds")
    )
    await say(c, await chat(c, VIEWER), "My timezone is Eastern and my city is Leeds.", VIEWER)
    assert [m["value"] for m in await mine(c, VIEWER)] == ["Leeds"], "only what the person's own words say"


async def test_an_unsure_memory_waits_as_a_suggestion_and_is_never_used(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    rt.memory_extractor = Answering(said("Eastern", confidence=0.6))
    await say(c, await chat(c, VIEWER), "I think my timezone is Eastern now.", VIEWER)
    assert await mine(c, VIEWER) == [] and "Eastern" not in await profile(rt)
    assert await statuses(rt) == [("Eastern", SUGGESTED)]


async def test_remember_that_saves_without_the_models_judgement_but_not_pasted_text(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    rt.memory_extractor = Answering()
    thread = await chat(c, VIEWER)
    await say(c, thread, "Remember that I sign off as Dee.", VIEWER)
    await say(c, thread, "Remember that " + "the quarterly figures are as follows " * 12, VIEWER)
    assert [(m["value"], m["confidence"]) for m in await mine(c, VIEWER)] == [("I sign off as Dee.", 1.0)]


async def test_remember_that_quoted_whole_saves_one_memory_the_person_asked_for(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    asked = "Remember that I prefer answers as short bullet points."
    rt.memory_extractor = Answering(
        said("Prefers answers as short bullet points", kind="preference", key="answer_style", quote=asked)
    )
    await say(c, await chat(c, VIEWER), asked, VIEWER)
    assert [(m["key"], m["source"], m["confidence"]) for m in await mine(c, VIEWER)] == [("answer style", "asked", 1.0)]


async def test_a_reworded_same_that_changes_a_confirmed_memory_replaces_it(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    rt.memory_extractor = Answering(said("short bullet points", kind="preference", key="answer style"))
    await say(c, await chat(c, VIEWER), "Remember that I prefer short bullet points.", VIEWER)
    kept = (await mine(c, VIEWER))[0]["id"]
    rt.memory_extractor = Answering(
        said("short numbered summaries", kind="preference", key="answer style", decision="same", ref=kept)
    )
    await say(c, await chat(c, VIEWER), "These days short numbered summaries suit me better.", VIEWER)
    assert [(r["value"], r["status"]) for r in await rows(rt)] == [
        ("short bullet points", SUPERSEDED),
        ("short numbered summaries", ACTIVE),
    ]


async def test_a_key_is_saved_as_words_however_the_model_wrote_it(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    rt.memory_extractor = Answering(
        said("short numbered lists", kind="preference", key="summaryFormatPreference"),
        said("Leeds", key="home_city"),
    )
    await say(c, await chat(c, VIEWER), "I like short numbered lists, and I live in Leeds.", VIEWER)
    assert sorted(m["key"] for m in await mine(c, VIEWER)) == ["home city", "summary format preference"]


async def test_a_short_turn_is_not_read_for_memory(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    rt.memory_extractor = extractor = Answering(said("EST"))
    await say(c, await chat(c, VIEWER), "My tz is EST", VIEWER)
    assert extractor.asked == [] and await mine(c, VIEWER) == []


async def test_a_hung_extraction_still_finishes_the_reply_and_saves_nothing(stack: Stack, monkeypatch: Any) -> None:  # noqa: F811
    c, rt = stack

    class Hung:
        async def structured(self, system: str, user: str, schema: dict[str, Any], *, key: str) -> Any:
            await asyncio.Event().wait()

    monkeypatch.setattr(memory_module, "EXTRACTION_DEADLINE_SECONDS", 0.05)
    rt.memory_extractor = Hung()
    events = await asyncio.wait_for(
        say(c, await chat(c, VIEWER), "My timezone is Eastern, for the record.", VIEWER), 10
    )
    assert any(e.get("type") == "done" for e in events), events
    assert await mine(c, VIEWER) == []


async def rows(rt: Any) -> list[dict[str, Any]]:
    """Every version of vera's memories, oldest first."""
    m = agent_memories
    with tenant_scope(TENANT):
        async with tenant_tx(graph_store(rt).engine) as conn:
            q = sa.select(m).where(m.c.person == "vera").order_by(m.c.created_at, m.c.id)
            return [dict(r) for r in (await conn.execute(q)).mappings()]


async def test_saying_it_again_confirms_instead_of_saving_twice(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    await say(c, await chat(c, VIEWER), "Hello. My timezone is Eastern.", VIEWER)
    await say(c, await chat(c, VIEWER), "As before, my timezone is Eastern.", VIEWER)
    kept = await rows(rt)
    assert [(r["value"], r["status"]) for r in kept] == [("Eastern", ACTIVE)], kept
    assert kept[0]["confirmed_at"], "said twice is confirmed"


async def test_a_changed_value_replaces_the_memory_and_keeps_its_history(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    await say(c, await chat(c, VIEWER), "Hello. My timezone is Eastern.", VIEWER)
    await say(c, await chat(c, VIEWER), "I moved, so my timezone is Pacific.", VIEWER)
    old, new = await rows(rt)
    assert (old["value"], old["status"], new["value"], new["status"]) == ("Eastern", SUPERSEDED, "Pacific", ACTIVE)
    assert new["supersedes_id"] == old["id"] and old["superseded_at"]


async def test_the_model_naming_a_memory_it_was_not_shown_changes_nothing_there(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    await say(c, await chat(c, BUILDER), "Hello. My timezone is Pacific.", BUILDER)
    theirs = (await mine(c, BUILDER))[0]["id"]
    rt.memory_extractor = Answering(said("Eastern", key="home zone", decision="replaces", ref=theirs))
    await say(c, await chat(c, VIEWER), "My home zone is Eastern, for my records.", VIEWER)
    assert [m["value"] for m in await mine(c, BUILDER)] == ["Pacific"], "another person's memory is untouched"
    new = (await rows(rt))[-1]
    assert (new["value"], new["status"], new["supersedes_id"]) == ("Eastern", ACTIVE, None), "saved as new"


async def test_an_unasked_contradiction_waits_and_the_confirmed_one_stays(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    await say(c, await chat(c, VIEWER), "Hello. My timezone is Eastern.", VIEWER)
    await say(c, await chat(c, VIEWER), "As before, my timezone is Eastern.", VIEWER)
    kept = (await mine(c, VIEWER))[0]["id"]
    rt.memory_extractor = Answering(said("Pacific", decision="conflicts", ref=kept))
    events = await say(c, await chat(c, VIEWER), "The meeting invite showed Pacific times.", VIEWER)
    assert [(r["value"], r["status"]) for r in await rows(rt)] == [("Eastern", ACTIVE), ("Pacific", CONFLICT)]
    text = await profile(rt)
    assert "Eastern" in text and "Pacific" not in text, text
    done: dict[str, Any] = next(e for e in events if e.get("type") == "done")["message"]
    assert [(m["value"], m["status"]) for m in done["remembered"]] == [("Pacific", CONFLICT)], done["remembered"]


async def test_undo_of_a_replacement_puts_the_old_memory_back(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    await say(c, await chat(c, VIEWER), "Hello. My timezone is Eastern.", VIEWER)
    await say(c, await chat(c, VIEWER), "I moved, so my timezone is Pacific.", VIEWER)
    new = (await rows(rt))[-1]
    with tenant_scope(TENANT):
        assert await Memories(graph_store(rt).engine).undo("vera", new["id"], actor="vera")
    assert [(r["value"], r["status"]) for r in await rows(rt)] == [("Eastern", ACTIVE), ("Pacific", FORGOTTEN)]
    assert "timezone: Eastern" in await profile(rt)


async def test_a_reload_reads_what_was_remembered_from_the_memory_not_the_thread(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    rt.memory_extractor = Answering(
        said("Answers as bullet points.", kind="procedure", key="answer style", quote="Answers as bullet points")
    )
    thread = await chat(c, VIEWER)
    await say(c, thread, "Answers as bullet points, as I always do.", VIEWER)
    with tenant_scope(TENANT):
        logged = [e.data for e in await EventLog(graph_store(rt).engine).for_threads([thread]) if e.type == "memory"]
    assert logged and "bullet" not in str(logged), "the thread keeps the memory's id, never its text"
    reloaded = [m for m in (await messages_of(rt, [thread], reader="vera"))[thread] if m.remembered]
    assert [(r.kind, r.value) for r in reloaded[0].remembered or []] == [("procedure", "Answers as bullet points.")]
    memory = (await mine(c, VIEWER))[0]
    assert (await c.delete(f"{MINE}/{memory['id']}", headers=VIEWER)).status_code == 204
    gone = next(m for m in (await messages_of(rt, [thread]))[thread] if m.remembered).remembered or []
    assert [(r.value, r.status) for r in gone] == [(None, FORGOTTEN)], gone


async def keep(rt: Any, key: str, value: str, *, kind: str = "fact", agent: str = EVERY_AGENT, team: str = TEAM) -> str:
    with tenant_scope(TENANT):
        row = await Memories(graph_store(rt).engine).save(
            team_id=team,
            agent_id=agent,
            person="vera",
            kind=kind,
            key=key,
            value=value,
            confidence=0.9,
            source="extraction",
            thread_id=None,
        )
    return str(row["id"])


def lines_of(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith("- [")]


async def test_recall_reads_only_the_acting_team_even_with_no_team_on_the_caller(stack: Stack) -> None:  # noqa: F811
    _, rt = stack
    await keep(rt, "branch", "Leeds Central")
    with tenant_scope(TENANT), acting_for(viewer()):
        other = await MemoryReads(rt).recall("vera", "team_other", "ag_branch", "which branch am I at")
    assert other is None, other.text if other else ""
    assert "Leeds Central" in await profile(rt, question="which branch am I at")


async def test_recall_keeps_to_its_budget_best_matches_first(stack: Stack) -> None:  # noqa: F811
    _, rt = stack
    for n in range(30):
        await keep(rt, f"branch note {n}", f"Branch fact number {n}." + (" wire" if n == 7 else ""))
    short = lines_of(await profile(rt, question="branch wire cut-off"))
    assert len(short) == 8 and "number 7. wire" in short[0], short
    for n in range(30):
        await keep(rt, f"long note {n}", f"Long branch note {n}: " + "detail " * 60)
    text = await profile(rt, question="long branch note")
    tokens = sum(-(-len(line) // 4) for line in lines_of(text))
    assert 0 < tokens <= 600 and len(lines_of(text)) < 8, (tokens, len(lines_of(text)))


async def test_a_memory_kept_to_one_agent_reaches_no_other(stack: Stack) -> None:  # noqa: F811
    _, rt = stack
    await keep(rt, "branch", "Leeds Central", agent="ag_branch")
    assert "Leeds Central" in await profile(rt, "ag_branch", "which branch")
    assert "Leeds Central" not in await profile(rt, "ag_dispute", "which branch")


async def test_a_turn_records_the_memory_versions_it_used(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    used = await keep(rt, "branch", "Leeds Central", kind="preference")
    thread = await chat(c, VIEWER)
    await say(c, thread, "Which branch should I visit this week?", VIEWER)
    u = message_memory_use.c
    with tenant_scope(TENANT):
        async with tenant_tx(graph_store(rt).engine) as conn:
            picked = (await conn.execute(sa.select(u.memory_id, u.reason).where(u.thread_id == thread))).all()
    assert [tuple(p) for p in picked] == [(used, "pinned")], picked
    fixed = await c.patch(f"{MINE}/{used}", json={"value": "York"}, headers=VIEWER)
    assert fixed.status_code == 200, fixed.text
    with tenant_scope(TENANT):
        then = (await Memories(graph_store(rt).engine).by_ids([used]))[used]
    assert (then["value"], then["status"]) == ("Leeds Central", SUPERSEDED), "the version used, as it was"
    assert then["use_count"] == 1 and then["last_used_at"]


async def test_a_forget_is_undone_within_its_grace_and_not_after(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    await say(c, await chat(c, VIEWER), "Hello. My timezone is Eastern.", VIEWER)
    memory = (await mine(c, VIEWER))[0]
    assert (await c.delete(f"{MINE}/{memory['id']}", headers=VIEWER)).status_code == 204
    assert (await c.post(f"{MINE}/{memory['id']}/undo", headers=BUILDER)).status_code == 404, "not another person's"
    assert (await c.post(f"{MINE}/{memory['id']}/undo", headers=VIEWER)).status_code == 204
    assert [m["value"] for m in await mine(c, VIEWER)] == ["Eastern"] and "Eastern" in await profile(rt)
    assert (await c.delete(f"{MINE}/{memory['id']}", headers=VIEWER)).status_code == 204
    m = agent_memories.c
    with tenant_scope(TENANT):
        async with tenant_tx(graph_store(rt).engine) as conn:
            await conn.execute(agent_memories.update().where(m.id == memory["id"]).values(erase_after="2000-01-01"))
    assert (await c.post(f"{MINE}/{memory['id']}/undo", headers=VIEWER)).status_code == 404, "past its grace"


async def test_undo_takes_back_what_a_reply_just_remembered(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    events = await say(c, await chat(c, VIEWER), "Hello. My timezone is Eastern.", VIEWER)
    done: dict[str, Any] = next(e for e in events if e.get("type") == "done")["message"]
    saved = done["remembered"][0]["id"]
    assert (await c.post(f"{MINE}/{saved}/undo", headers=VIEWER)).status_code == 204
    assert await mine(c, VIEWER) == [] and "Eastern" not in await profile(rt)
    audit = (await c.get(f"{MINE}/export", headers=VIEWER)).json()["data"]["audit"]
    assert [(a["action"], a.get("teamId", a.get("team_id"))) for a in audit if a["action"] == "undo"] == [
        ("undo", TEAM)
    ], audit


async def test_erase_removes_a_memory_and_its_earlier_versions_at_once(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    thread = await chat(c, VIEWER)
    await say(c, thread, "Hello. My timezone is Eastern.", VIEWER)
    await say(c, await chat(c, VIEWER), "I moved, so my timezone is Pacific.", VIEWER)
    current = (await mine(c, VIEWER))[0]
    assert (await c.post(f"{MINE}/{current['id']}/erase", headers=VIEWER)).status_code == 204
    assert await rows(rt) == [], "no version keeps its text"
    reloaded = next(m for m in (await messages_of(rt, [thread]))[thread] if m.remembered).remembered or []
    assert [(r.value, r.status) for r in reloaded] == [(None, FORGOTTEN)]
    assert (await c.post(f"{MINE}/{current['id']}/undo", headers=VIEWER)).status_code == 404, "an erase is final"


async def test_words_the_person_pasted_quoted_or_said_earlier_are_not_learned(stack: Stack) -> None:  # noqa: F811
    # gpt-5-mini kept a preference from a pasted instruction (experiments/memory-decisions.md, 2026-10-29).
    c, rt = stack
    rt.memory_extractor = Answering(
        said("I prefer to be called Bob", kind="preference", key="name", quote="I prefer to be called Bob"),
        said("letters", kind="preference", key="channel", quote="I prefer letters to email"),
    )
    thread = await chat(c, VIEWER)
    await say(c, thread, "The customer wrote: I prefer letters to email. Can you look at it?", VIEWER)
    await say(c, thread, "Here is their email:\n> I prefer to be called Bob.\nPlease draft a reply.", VIEWER)
    assert await mine(c, VIEWER) == [], "only the person's own words in their latest message"


async def test_an_episode_or_a_case_is_not_learned_from_a_turn(stack: Stack) -> None:  # noqa: F811
    # gpt-5-mini kept an episode from a question, and a case from a request to draft a reply.
    c, rt = stack
    message = "Please draft a reply to the customer about the disputed card charge."
    rt.memory_extractor = Answering(
        said(message, kind="episode", key="", quote=message),
        said("Disputed card charge", kind="case", key="dispute", quote="the disputed card charge"),
    )
    await say(c, await chat(c, VIEWER), message, VIEWER)
    assert await statuses(rt) == []


async def test_a_turn_makes_one_decision_per_memory(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    rt.memory_extractor = Answering(
        said("Eastern", quote="my timezone is Eastern"), said("Pacific", quote="later Pacific")
    )
    await say(c, await chat(c, VIEWER), "Hi, my timezone is Eastern, and later Pacific.", VIEWER)
    assert [r["value"] for r in await rows(rt)] == ["Eastern"], "one memory per key from one turn"
