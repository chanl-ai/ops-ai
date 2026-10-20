"""The built-in present tool on the chat (c-055 T021), by failure mode: the part never reaching the stream, a tool
card shown for a call that ran nothing, and the part lost on reload."""

from __future__ import annotations

import json
from typing import Any

from httpx import AsyncClient

from tests.conftest import sse_events

ROWS = [{"product": "Savings Plus", "rate": 3.1}, {"product": "Money Market", "rate": 3.65}]


async def test_a_presented_table_arrives_as_a_rows_part_with_no_tool_card(client: AsyncClient) -> None:
    thread = (await client.post("/chat/threads", json={"agentId": "ag_fraud", "kbIds": []})).json()
    tid = thread["data"]["id"]
    ask = f"call present {json.dumps({'shape': 'rows', 'data': ROWS, 'hint': {'title': 'Compared'}})}"
    res = await client.post(
        f"/chat/threads/{tid}/messages", json={"content": ask}, headers={"Accept": "text/event-stream"}
    )
    assert res.status_code == 200, res.text
    events = sse_events(res.text)
    parts = [e["part"] for e in events if e.get("type") == "part"]
    assert len(parts) == 1 and parts[0]["shape"] == "rows" and parts[0]["data"] == ROWS
    assert parts[0]["hint"] == {"title": "Compared"} and parts[0]["id"].startswith("wp_")
    assert not [e for e in events if e.get("type") in ("tool_start", "tool_end")], "no tool card for a built-in"
    # Kept on reload, as the part, with no tool call behind it.
    saved = (await client.get(f"/chat/threads/{tid}")).json()["data"]["messages"]
    reply = saved[-1]
    kept: list[dict[str, Any]] = list(reply.get("parts") or [])
    assert [p["shape"] for p in kept] == ["rows"] and not reply.get("toolCalls")
