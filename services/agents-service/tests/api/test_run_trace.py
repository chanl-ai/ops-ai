"""The run trace, by its one failure mode (automatic-mode-and-loop-kinds.md, row 8): the mode a trace shows differs
from the mode the run's stream sent."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from tests.api.test_action_roles import VIEWER
from tests.api.test_ask_first_chat import (
    LOOSE,
    chat,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from tests.api.test_chat_owner_only import chat_with_a_run
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.api.test_write_approval_policy import WRITE, person
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
    # Why the turn ended, as the kernel named it: an answer is `final`, never the run's status.
    assert trace.json()["data"]["stopReason"] == "final", trace.json()["data"]


async def test_a_planned_change_streams_its_plan_before_the_write_and_done_names_the_modes(
    chat: AsyncClient,  # noqa: F811
) -> None:
    james = person("usr_james", ["team_ops"], role="approver", policies=LOOSE)
    made = await chat.post("/chat/threads", json={"agentId": "ag_dispute", "kbIds": []}, headers=james)
    thread = str(made.json()["data"]["id"])
    sent = await chat.post(
        f"/chat/threads/{thread}/messages", json={"content": WRITE}, headers={**james, "Accept": "text/event-stream"}
    )
    events = sse_events(sent.text)
    kinds = [e["type"] for e in events]
    plan = next(e for e in events if e["type"] == "plan")
    assert plan["steps"] and {s["status"] for s in plan["steps"]} <= {"pending", "doing", "done", "skipped"}, plan
    # The held write is the first frame that names it; the plan comes before it.
    write = next(i for i, e in enumerate(events) if e.get("call", {}).get("name") == "request_document")
    assert kinds.index("plan") < write, kinds
    done = next(e for e in events if e["type"] == "done")
    assert [m["mode"] for m in done["modes"]] == [e["mode"] for e in events if e["type"] == "mode"], done["modes"]
    assert "plan" in [m["mode"] for m in done["modes"]], done["modes"]
