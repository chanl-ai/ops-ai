"""A generic widget kind through a real chat turn (c-176): the part the kernel fills must reach the stream and survive a
reload, or the turn breaks with a 500 when the chat contract does not know the part's `kind`."""

from __future__ import annotations

import json
from typing import Any, cast

from httpx import AsyncClient

from ops_agents.api.deps import Runtime
from tests.api.test_child_runs import stack  # noqa: F401  # pyright: ignore[reportUnusedImport] - the shared app fixture
from tests.conftest import sse_events

TRACKER = {"kind": "tracker", "data": {"title": "Order 88213", "steps": [{"label": "Packed", "state": "done"}]}}


async def test_a_kind_reaches_the_stream_and_a_reload(stack: tuple[AsyncClient, Runtime]) -> None:  # noqa: F811
    client, _ = stack
    tid = (await client.post("/chat/threads", json={"agentId": "ag_branch", "kbIds": []})).json()["data"]["id"]
    res = await client.post(f"/chat/threads/{tid}/messages", json={"content": f"call present {json.dumps(TRACKER)}"})
    assert res.status_code == 200, res.text
    parts = [e["part"] for e in sse_events(res.text) if e.get("type") == "part"]
    assert [(p.get("kind"), p["layout"]["title"]) for p in parts] == [("tracker", "Order 88213")], sse_events(res.text)
    messages: list[dict[str, Any]] = (await client.get(f"/chat/threads/{tid}")).json()["data"]["messages"]
    kept = [cast(dict[str, Any], p) for m in messages for p in cast(list[Any], m.get("parts") or [])]
    assert [p.get("kind") for p in kept] == ["tracker"], "a reload draws the same kind"
