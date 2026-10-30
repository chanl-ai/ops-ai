"""Memory text is its owner's alone (c-563), by failure mode: a person allowed to read another's thread (an admin, with
owner-only threads off) sees what the assistant remembered about them; or a response to the owner, such as the budget
answer, drops their own memory text."""

from __future__ import annotations

from typing import Any, cast

import pytest
from httpx import AsyncClient

from ops_metering import Budget
from tests.api.test_action_roles import VIEWER
from tests.api.test_chat_budget import OWNER, rt_of
from tests.api.test_chat_owner_only import chat_reader_role, reader  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.api.test_memory import chat
from tests.api.test_team_default_agent import Stack, say, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.api.test_write_approval_policy import (
    dev_platform,  # noqa: F401  # pyright: ignore[reportUnusedImport] - fixture
)


def remembered(thread: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = thread["messages"]
    return [r for m in messages for r in cast(list[dict[str, Any]], m.get("remembered") or [])]


@pytest.mark.usefixtures("chat_reader_role")
async def test_another_reader_of_a_thread_sees_that_something_was_remembered_never_what(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    thread = await chat(c, VIEWER)
    await say(c, thread, "Hello. My timezone is Eastern.", VIEWER)
    mine = remembered((await c.get(f"/chat/threads/{thread}", headers=VIEWER)).json()["data"])
    assert [(r.get("key"), r.get("value")) for r in mine] == [("timezone", "Eastern")], "the owner sees it"
    shown = await c.get(f"/chat/threads/{thread}", headers=reader({"chatThreadsOwnerOnly": False}))
    assert shown.status_code == 200, shown.text
    theirs = remembered(shown.json()["data"])
    assert [(r.get("kind"), r.get("status")) for r in theirs] == [("fact", "active")], theirs
    assert all(r.get("key") is None and r.get("value") is None for r in theirs), "never the key or the value"


async def test_the_budget_answer_keeps_the_owners_memory_text(dev_platform: AsyncClient) -> None:  # noqa: F811
    made = await dev_platform.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": []}, headers=OWNER)
    tid = made.json()["data"]["id"]
    stream = {**OWNER, "Accept": "text/event-stream"}
    first = await dev_platform.post(
        f"/chat/threads/{tid}/messages", json={"content": "Hello. My timezone is Eastern."}, headers=stream
    )
    assert first.status_code == 200, first.text
    rt = rt_of(dev_platform)
    assert rt.usage is not None
    await rt.usage.set_budget(tid, Budget(max_calls=1))
    await dev_platform.post(f"/chat/threads/{tid}/messages", json={"content": "And what else?"}, headers=stream)
    answered = await dev_platform.post(f"/chat/threads/{tid}/budget", json={"action": "continue"}, headers=OWNER)
    assert answered.status_code == 200, answered.text
    kept = remembered(answered.json()["data"])
    assert [r.get("value") for r in kept] == ["Eastern"], kept
