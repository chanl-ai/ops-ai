"""Chat as the chat screen calls it: agents-service's `/v1/chat/*` routes. They are left out of the OpenAPI document,
so the generated layer has none of them; each is declared here as an operation and sent through the same transport.

A reply streams as server-sent events, each a JSON object with a `type`: `status` (a phase), `text` (a delta),
`replace` (the whole text so far), `tool_end` (a finished tool call), `widget`, `error` and `done` (the stored
message). A tool call refused with `CONNECTION_NOT_LINKED` is the Connect card the screen shows; `connect_card`
reads it."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any, cast

from ._transport import Operation, page_items

SERVICE = "agents"
LINKED = "CONNECTION_NOT_LINKED"
ACTIONS = ("approve", "reject", "submit")


def _op(method: str, path: str, *params: str, stream: bool = False) -> Operation:
    body = "json" if method in ("POST", "PUT", "PATCH") else None
    return {
        "method": method,
        "path": path,
        "pathParams": list(params),
        "query": [],
        "headers": [],
        "body": body,
        "stream": stream,
    }


OPERATIONS: dict[str, Operation] = {
    "agents": _op("GET", "/v1/chat/agents"),
    "default_agent": _op("GET", "/v1/chat/default-agent"),
    "threads": _op("GET", "/v1/chat/threads"),
    "create": _op("POST", "/v1/chat/threads"),
    "get": _op("GET", "/v1/chat/threads/{thread_id}", "thread_id"),
    "update": _op("PATCH", "/v1/chat/threads/{thread_id}", "thread_id"),
    "delete": _op("DELETE", "/v1/chat/threads/{thread_id}", "thread_id"),
    "send": _op("POST", "/v1/chat/threads/{thread_id}/messages", "thread_id", stream=True),
    "feedback": _op("PUT", "/v1/chat/threads/{thread_id}/messages/{message_id}/feedback", "thread_id", "message_id"),
    "widget_action": _op(
        "POST",
        "/v1/chat/threads/{thread_id}/messages/{message_id}/widgets/{widget_id}/actions",
        "thread_id",
        "message_id",
        "widget_id",
    ),
    "budget": _op("POST", "/v1/chat/threads/{thread_id}/budget", "thread_id"),
}


def thread_body(agent: str | None = None, *, kb_ids: list[str] | None = None, test: bool = False) -> dict[str, Any]:
    """New chat's body: no agent starts on the team's default; `test` is an agent page's Test panel, which runs the
    agent's newest version, published or not."""
    body: dict[str, Any] = {"kbIds": list(kb_ids or [])}
    if agent:
        body["agentId"] = agent
    if test:
        body["test"] = True
    return body


def action_body(action: str, *, reason: str | None = None, values: dict[str, str] | None = None) -> dict[str, Any]:
    """A widget's action as its buttons send it: approve, reject with a reason, or submit the form's values."""
    if action == "approve":
        return {"type": "approve"}
    if action == "reject":
        if not reason:
            raise ValueError("a reject needs a reason, as the widget asks for one")
        return {"type": "reject", "reason": reason}
    if action == "submit":
        return {"type": "submit", "values": dict(values or {})}
    raise ValueError(f"a widget action is one of {', '.join(ACTIONS)}, not {action}")


def connect_card(call: dict[str, Any]) -> dict[str, Any] | None:
    """The Connect card a failed tool call shows: the app to connect, why, and the sign-in link."""
    out = call.get("output")
    error = out.get("error") if isinstance(out, dict) else None
    if isinstance(error, dict) and isinstance(error.get("error"), dict):
        error = error["error"]
    if call.get("status") != "failed" or not isinstance(error, dict) or error.get("code") != LINKED:
        return None
    return {**(error.get("details") or {}), "message": error.get("message", "")}


def _data(events: Any) -> Iterator[dict[str, Any]]:
    for e in events:
        if isinstance(e.get("data"), dict):
            yield cast(dict[str, Any], e["data"])


class Chat:
    def __init__(self, raw: Any) -> None:
        self._t = raw.agents._t

    def _call(self, name: str, path: dict[str, Any] | None = None, body: Any = None, **query: Any) -> Any:
        return self._t.call(SERVICE, OPERATIONS[name], path or {}, query, {}, body)

    def agents(self) -> list[dict[str, Any]]:
        """The agents New chat offers this person."""
        return page_items(self._call("agents"))[0]

    def default_agent(self) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("default_agent"))

    def threads(self, **query: Any) -> list[dict[str, Any]]:
        """One page of the person's conversations, newest first (page, pageSize, search, cursor)."""
        return page_items(self._call("threads", **query))[0]

    def start(self, agent: str | None = None, *, kb_ids: list[str] | None = None, test: bool = False) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("create", body=thread_body(agent, kb_ids=kb_ids, test=test)))

    def get(self, thread: str) -> dict[str, Any]:
        """The conversation as the chat reads it: its messages, each with its tool calls and widgets."""
        return cast(dict[str, Any], self._call("get", {"thread_id": thread}))

    def say(self, thread: str, text: str) -> Iterator[dict[str, Any]]:
        """Sends a message and yields the reply's events as they stream."""
        return _data(self._call("send", {"thread_id": thread}, {"content": text}))

    def act(self, thread: str, message: str, widget: str, action: dict[str, Any]) -> dict[str, Any]:
        """A widget's action (`action_body`); answers the widget in its new state."""
        path = {"thread_id": thread, "message_id": message, "widget_id": widget}
        return cast(dict[str, Any], self._call("widget_action", path, action))

    def feedback(self, thread: str, message: str, feedback: str | None) -> Any:
        return self._call("feedback", {"thread_id": thread, "message_id": message}, {"feedback": feedback})

    def remove(self, thread: str) -> Any:
        return self._call("delete", {"thread_id": thread})


class AsyncChat:
    def __init__(self, raw: Any) -> None:
        self._t = raw.agents._t

    async def _call(self, name: str, path: dict[str, Any] | None = None, body: Any = None, **query: Any) -> Any:
        return await self._t.call(SERVICE, OPERATIONS[name], path or {}, query, {}, body)

    async def agents(self) -> list[dict[str, Any]]:
        return page_items(await self._call("agents"))[0]

    async def default_agent(self) -> dict[str, Any]:
        return cast(dict[str, Any], await self._call("default_agent"))

    async def threads(self, **query: Any) -> list[dict[str, Any]]:
        return page_items(await self._call("threads", **query))[0]

    async def start(
        self, agent: str | None = None, *, kb_ids: list[str] | None = None, test: bool = False
    ) -> dict[str, Any]:
        return cast(dict[str, Any], await self._call("create", body=thread_body(agent, kb_ids=kb_ids, test=test)))

    async def get(self, thread: str) -> dict[str, Any]:
        return cast(dict[str, Any], await self._call("get", {"thread_id": thread}))

    async def say(self, thread: str, text: str) -> AsyncIterator[dict[str, Any]]:
        async for e in await self._call("send", {"thread_id": thread}, {"content": text}):
            if isinstance(e.get("data"), dict):
                yield cast(dict[str, Any], e["data"])

    async def act(self, thread: str, message: str, widget: str, action: dict[str, Any]) -> dict[str, Any]:
        path = {"thread_id": thread, "message_id": message, "widget_id": widget}
        return cast(dict[str, Any], await self._call("widget_action", path, action))

    async def feedback(self, thread: str, message: str, feedback: str | None) -> Any:
        return await self._call("feedback", {"thread_id": thread, "message_id": message}, {"feedback": feedback})

    async def remove(self, thread: str) -> Any:
        return await self._call("delete", {"thread_id": thread})
