"""What a person sees of memory in the chat (c-206), by failure mode: a reply that saved a memory says nothing, live or
after a reload; a reply that saved nothing claims it did."""

from __future__ import annotations

from typing import Any, cast

from tests.api.test_action_roles import VIEWER
from tests.api.test_memory import chat
from tests.api.test_team_default_agent import Stack, say, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]


def done(events: list[dict[str, Any]]) -> dict[str, Any]:
    return next(e for e in events if e.get("type") == "done")["message"]


def remembered(message: dict[str, Any]) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], message.get("remembered") or [])


async def test_a_reply_says_what_it_saved_live_and_after_a_reload(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    thread = await chat(c, VIEWER)
    live = done(await say(c, thread, "My timezone is Eastern.", VIEWER))
    saved = [(m["key"], m["value"]) for m in remembered(live)]
    assert saved == [("timezone", "Eastern")], live
    plain = done(await say(c, thread, "What is the branch hours?", VIEWER))
    assert not remembered(plain), "a reply that saved nothing says nothing"
    r = await c.get(f"/v1/chat/threads/{thread}", headers=VIEWER)
    replies: list[dict[str, Any]] = [m for m in r.json()["data"]["messages"] if m["role"] == "assistant"]
    assert [[x["value"] for x in remembered(m)] for m in replies] == [["Eastern"], []], replies
