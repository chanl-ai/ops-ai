"""A chain tried in an agent's Test panel, by failure mode: a specialist granted on the draft alone is not offered
until the agent is published, so a builder cannot try it."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient

from tests.conftest import scripted_model, sse_events
from tests.engine.test_lifecycle_rights import BUILDER

from .role_app import ok, role_app

ASKER = "ag_branch"
ASK = 'call agent__ag_dispute {"question": "Can I dispute a card charge?"}'


@pytest.fixture
async def c() -> AsyncIterator[AsyncClient]:
    async with role_app(scripted_model()) as client:
        yield client


async def _draft(c: AsyncClient) -> int:
    """Saves the asker holding `agent:ag_dispute` and does not publish it; the draft's version."""
    held: list[str] = ok(await c.get(f"/v1/agents/{ASKER}", headers=BUILDER))["toolIds"]
    body = {"toolIds": [*held, "agent:ag_dispute"]}
    return int(ok(await c.patch(f"/v1/agents/{ASKER}", json=body, headers=BUILDER))["version"])


async def _turn(c: AsyncClient, *, test: bool) -> tuple[list[dict[str, Any]], str]:
    """One message asking for the specialist on a new thread: the tool calls that ended, and the reply."""
    made = await c.post("/chat/threads", json={"agentId": ASKER, "kbIds": [], "test": test}, headers=BUILDER)
    res = await c.post(
        f"/chat/threads/{ok(made, 201)['id']}/messages",
        json={"content": ASK},
        headers={**BUILDER, "Accept": "text/event-stream"},
    )
    assert res.status_code == 200, res.text
    events = sse_events(res.text)
    done = [e for e in events if e.get("type") in ("done", "error")]
    assert done and done[-1]["type"] == "done", done
    return [e["call"] for e in events if e.get("type") == "tool_end"], str(done[-1]["message"]["content"])


async def test_a_specialist_granted_on_the_draft_answers_in_the_test_panel_and_not_in_chat(c: AsyncClient) -> None:
    draft = await _draft(c)
    calls, _ = await _turn(c, test=True)
    asked = [(call["name"], call["output"].get("status"), call["output"].get("path", [None])[0]) for call in calls]
    # The chain names the version that asked: the draft under test, not the published one.
    assert asked == [("agent__ag_dispute", "answered", f"{ASKER}@v{draft}")], calls
    live, _ = await _turn(c, test=False)
    assert live == [], "a chat on the published version asked a specialist only the draft holds"
