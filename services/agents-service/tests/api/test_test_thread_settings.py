"""A test thread of an agent that was never published still opens its chat panels: the connectors picker and the
settings panel read the agent the test runs (the saved draft), not only the live catalog, which has no draft."""

from __future__ import annotations

from httpx import AsyncClient

from tests.engine.test_lifecycle_rights import BUILDER

from .role_app import ok
from .test_test_threads import Recorder, stack

__all__ = ["stack"]


async def test_connectors_and_settings_open_on_a_test_thread_of_a_draft_agent(
    stack: tuple[AsyncClient, Recorder],
) -> None:
    c, _ = stack
    draft = ok(await c.post("/v1/agents", json={"name": "Draft desk", "role": "Answers"}, headers=BUILDER), 201)
    made = await c.post("/chat/threads", json={"agentId": draft["id"], "kbIds": [], "test": True}, headers=BUILDER)
    tid = ok(made, 201)["id"]
    for path in ("connectors", "settings"):
        res = await c.get(f"/chat/threads/{tid}/{path}", headers=BUILDER)
        assert res.status_code == 200, (path, res.text)
