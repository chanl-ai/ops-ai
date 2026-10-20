"""What agents remember about each person (c-124), by failure mode: another person's, agent's or tenant's memory loaded
or listed; a memory written from a tool result or the agent's reply; a forgotten memory still loaded or found, or the
forget not recorded; memory off or a switched-off kind still saved; a corrected fact still loading its old value; a
low-confidence guess saved. Tokens carry roles as platform-service mints them; the scripted model answers extraction."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

from httpx import AsyncClient

from ops_agents.api.auth import Principal
from ops_agents.api.chat_threads import messages_of
from ops_agents.api.child_runs import acting_for
from ops_agents.api.engine_agents import KernelModels
from ops_agents.api.memory import MemoryReads, remember_turn
from ops_agents.store.tenancy import tenant_scope
from tests.api.test_action_roles import BUILDER, OUTSIDER, VIEWER
from tests.api.test_team_default_agent import Stack, say, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.api.test_team_default_agent import viewer as viewer_by_email
from tests.engine.test_lifecycle_rights import TENANT

MINE = "/v1/me/memories"


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


async def profile(rt: Any, agent: str = "ag_branch") -> str:
    with tenant_scope(TENANT), acting_for(viewer()):
        fragment = await MemoryReads(rt).profile(agent)
    return fragment.text if fragment else ""


def tool_outputs(events: list[dict[str, Any]]) -> str:
    return str([e["call"].get("output") for e in events if e.get("type") == "tool_end"])


async def test_a_memory_follows_its_person_and_agent_only(stack: Stack) -> None:  # noqa: F811
    c, rt = stack
    await say(c, await chat(c, VIEWER), "Hi. My timezone is Eastern.", VIEWER)
    assert [(m["key"], m["value"]) for m in await mine(c, VIEWER, "ag_branch")] == [("timezone", "Eastern")]
    assert "timezone: Eastern" in await profile(rt), "the next chat with the agent knows it"
    assert await mine(c, BUILDER) == [] and await mine(c, OUTSIDER) == [], "no one else sees it"
    assert await mine(c, VIEWER, "ag_dispute") == [] and await profile(rt, "ag_dispute") == "", "nor another agent"
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
    await say(c, await chat(c, VIEWER), message, VIEWER)
    assert seen == [f"<remember>\n{message}\n</remember>"], "the extractor reads the message, not the tool or the reply"


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
            return {"memories": [{"kind": "fact", "key": "timezone", "value": "Eastern", "confidence": 0.95}]}

    rt.memory_extractor = Watching()
    events = await say(c, await chat(c, VIEWER), "My timezone is Eastern.", VIEWER)
    assert replies_when_read == [0], "the extraction starts before the reply is written"
    done: dict[str, Any] = next(e for e in events if e.get("type") == "done")["message"]
    kept = cast(list[dict[str, Any]], done.get("remembered") or [])
    assert [m["value"] for m in kept] == ["Eastern"], "and the reply still says what it kept"
