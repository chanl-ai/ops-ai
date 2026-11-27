"""The chat routes test_reply_pins.py does not reach, pinned key by key, and a turn whose reader went away: it still
finishes, so its model calls and cost are recorded and its lease is let go. `AGENTS_REPIN=1` rewrites the fixture."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.types import Message

from ops_agent_kernel.testing import Answer
from ops_service_kit.http import Json
from tests.conftest import empty_engine, scripted, sse_events
from tests.model_gateway import through_gateway

from .test_reply_pins import FIXTURES, answer, compare

NEW = {"agentId": "ag_fraud", "kbIds": ["kb_people"]}
ANSWER = "The daily wire limit for a personal account is $25,000 online [1]."
QUESTION = "What is the daily wire limit for a personal account?"


async def test_the_other_chat_routes_keep_every_key_value_and_error_object(client: httpx.AsyncClient) -> None:
    c = client
    seen: dict[str, Any] = {}
    seen["default.read"] = answer(await c.get("/chat/default-agent"))
    seen["default.set"] = answer(await c.put("/chat/default-agent", json={"agentId": "ag_fraud"}))
    seen["default.notLive"] = answer(await c.put("/chat/default-agent", json={"agentId": "ag_missing"}))
    seen["default.readAfter"] = answer(await c.get("/chat/default-agent"))
    one = (await c.post("/chat/threads", json=NEW)).json()["data"]["id"]
    two = (await c.post("/chat/threads", json=NEW)).json()["data"]["id"]
    seen["patch"] = answer(await c.patch(f"/chat/threads/{one}", json={"title": "Wire limits", "pinned": True}))
    seen["patchMissing"] = answer(await c.patch("/chat/threads/th_missing", json={"title": "x"}))
    seen["recent"] = answer(await c.get("/chat/threads", params={"recent": 1, "pageSize": 5}))
    seen["recentRefused"] = answer(await c.get("/chat/threads", params={"recent": 1, "sortBy": "title"}))
    first = (await c.get("/chat/threads", params={"pageSize": 1})).json()
    seen["cursorPage"] = answer(
        await c.get("/chat/threads", params={"pageSize": 1, "cursor": first["data"]["nextCursor"]})
    )
    seen["cursorRefused"] = answer(await c.get("/chat/threads", params={"pageSize": 1, "cursor": "bm90LW91cnM="}))
    seen["bulkUpdate"] = answer(
        await c.post("/chat/threads/bulk-update", json={"ids": [two, "th_missing"], "patch": {"archived": True}})
    )
    seen["feedbackMissing"] = answer(
        await c.put(f"/chat/threads/{one}/messages/msg_missing/feedback", json={"feedback": {"rating": "up"}})
    )
    seen["widgetMissing"] = answer(
        await c.post(f"/chat/threads/{one}/messages/msg_missing/widgets/w1/actions", json={"type": "approve"})
    )
    seen["delete"] = {"status": (await c.delete(f"/chat/threads/{one}")).status_code}
    seen["deleteMissing"] = answer(await c.delete("/chat/threads/th_missing"))
    seen["bulkDelete"] = answer(await c.post("/chat/threads/bulk-delete", json={"ids": [two, one, "th_missing"]}))
    seen["afterDelete"] = answer(await c.get("/chat/threads", params={"pageSize": 5}))
    compare(seen, FIXTURES / "reply-pins-chat-routes.json")


class HeldModel:
    """The scripted model, held at its first answer until `go` is set."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine, self.asked, self.held = engine, asyncio.Event(), asyncio.Event()
        self.go = asyncio.Event()

    async def answer(self, messages: list[Json], tools: list[Json]) -> Answer:
        self.asked.set()
        await self.go.wait()
        return scripted(messages, tools)


async def _send_and_leave(app: FastAPI, thread_id: str, held: HeldModel) -> list[bytes]:
    """POST a message straight to the ASGI app (httpx's transport waits for the whole reply, so it cannot leave) and
    go away once the model has been asked: the app is told the client disconnected."""
    body = json.dumps({"content": QUESTION}).encode()
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": f"/chat/threads/{thread_id}/messages",
        "raw_path": f"/chat/threads/{thread_id}/messages".encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"test"),
            (b"content-type", b"application/json"),
            (b"accept", b"text/event-stream"),
            (b"content-length", str(len(body)).encode()),
        ],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }
    read = False
    frames: list[bytes] = []

    async def receive() -> Message:
        nonlocal read
        if not read:
            read = True
            return {"type": "http.request", "body": body, "more_body": False}
        await held.asked.wait()
        return {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        if message["type"] == "http.response.body" and message.get("body"):
            frames.append(message["body"])

    await asyncio.wait_for(app(scope, receive, send), 10)
    return frames


async def test_a_turn_finishes_and_is_counted_when_its_reader_leaves(database_url: str, graph_models: Any) -> None:
    # Through the gateway in process: a reply's usage is read from the gateway's call log.
    async with empty_engine(database_url) as engine:
        held = HeldModel(engine)
        async with through_gateway(engine, graph_models, held.answer) as g:
            app, c = g.app, g.client
            tid = (await c.post("/chat/threads", json=NEW)).json()["data"]["id"]
            await _send_and_leave(app, tid, held)
            held.go.set()
            # The turn goes on without its reader: its reply is kept and its model calls are counted.
            thread: dict[str, Any] = {}
            for _ in range(100):
                thread = (await c.get(f"/chat/threads/{tid}")).json()["data"]
                last: dict[str, Any] = thread["messages"][-1] if thread["messages"] else {}
                if last.get("role") == "assistant" and last.get("content") == ANSWER and last.get("usage"):
                    break
                await asyncio.sleep(0.05)
            reply: dict[str, Any] = thread["messages"][-1]
            assert (reply["role"], reply["content"]) == ("assistant", ANSWER), thread["messages"]
            assert reply["usage"]["calls"] >= 1, reply
            # Its lease was let go: the next message on the thread is answered.
            again = await c.post(
                f"/chat/threads/{tid}/messages", json={"content": QUESTION}, headers={"Accept": "text/event-stream"}
            )
            assert again.status_code == 200 and sse_events(again.text)[-1]["type"] == "done", again.text
