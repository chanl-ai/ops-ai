"""The run trace, by its one failure mode (automatic-mode-and-loop-kinds.md, row 8): the mode a trace shows differs
from the mode the run's stream sent."""

from __future__ import annotations

from typing import Any

from tests.api.test_action_roles import VIEWER
from tests.api.test_chat_owner_only import chat_with_a_run
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.conftest import sse_events


async def test_the_traces_mode_steps_equal_the_mode_events_of_the_same_run(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    thread, run = await chat_with_a_run(c)
    log = await c.get(f"/v1/threads/{thread}/runs/{run}/events?follow=false", headers=VIEWER)
    sent: list[dict[str, Any]] = [e["data"] for e in sse_events(log.text) if e["type"] == "mode"]
    trace = await c.get(f"/v1/threads/{thread}/runs/{run}/trace", headers=VIEWER)
    assert trace.status_code == 200, trace.text
    shown = trace.json()["data"]["modes"]
    assert sent, "the run streamed no mode"
    assert [(m["mode"], m["reason"], m["fixed"]) for m in shown] == [(m["mode"], m["reason"], m["fixed"]) for m in sent]
