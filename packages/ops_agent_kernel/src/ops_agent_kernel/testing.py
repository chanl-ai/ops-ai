"""A scripted model at the HTTP edge: an `httpx2` transport that answers the OpenAI chat-completions route, streamed or
not, from a Python function `(messages, tools) -> reply`. Tests inject it as the model endpoint's HTTP client
(`ModelsServiceModels(..., http_client=httpx2.AsyncClient(transport=ScriptedModel(script)))`), so a test drives the
loop through the same wire any loop library speaks and never patches the library itself
(docs/design/agents-v2/runtime-contract-and-strands-loop.md, "The scripted model").

The transport is `httpx2` because the OpenAI SDK the loop's model client is built on imports it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

import httpx2

from ops_service_kit.http import Json


@dataclass(frozen=True)
class ToolCall:
    """One tool call in a scripted reply. With no `id`, one is derived from the conversation's length and the call, so a
    repeated request gets the same id and a later step a new one."""

    name: str
    arguments: dict[str, Any] = field(default_factory=lambda: {})
    id: str | None = None


@dataclass(frozen=True)
class Reply:
    """What the scripted model answers: text, tool calls, or both. `status` other than 200 answers with `error` as the
    body instead, as the model gateway refuses a call (429 `budget_reached`)."""

    text: str = ""
    tool_calls: Sequence[ToolCall] = ()
    input_tokens: int = 10
    output_tokens: int = 5
    status: int = 200
    error: Json | None = None


@dataclass(frozen=True)
class Structured:
    """A structured answer, written the way the request asks for one: a call of the request's output tool
    (`final_result`) when it offers one, else the JSON as text (a native response format)."""

    value: Json
    tool: str = "final_result"


Answer = Reply | Structured | str
Script = Callable[[list[Json], list[Json]], Answer | Awaitable[Answer]]

COMPLETIONS = "/chat/completions"


def tool_names(tools: Sequence[Json]) -> set[str]:
    """The names of the functions a request offers."""
    out: set[str] = set()
    for t in tools:
        fn = t.get("function")
        if isinstance(fn, dict) and isinstance(name := cast(Json, fn).get("name"), str):
            out.add(name)
    return out


def _reply(answer: Answer, tools: Sequence[Json]) -> Reply:
    if isinstance(answer, str):
        return Reply(text=answer)
    if isinstance(answer, Structured):
        if answer.tool in tool_names(tools):
            return Reply(tool_calls=[ToolCall(answer.tool, answer.value)])
        return Reply(text=json.dumps(answer.value))
    return answer


def _call_id(depth: int, index: int, call: ToolCall) -> str:
    if call.id:
        return call.id
    seed = json.dumps([depth, index, call.name, call.arguments], sort_keys=True, default=str)
    return f"call_{hashlib.sha256(seed.encode()).hexdigest()[:16]}"


def _wire_calls(reply: Reply, depth: int) -> list[Json]:
    return [
        {
            "id": _call_id(depth, i, c),
            "type": "function",
            "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
        }
        for i, c in enumerate(reply.tool_calls)
    ]


def _usage(reply: Reply) -> Json:
    return {
        "prompt_tokens": reply.input_tokens,
        "completion_tokens": reply.output_tokens,
        "total_tokens": reply.input_tokens + reply.output_tokens,
    }


class ScriptedModel(httpx2.AsyncBaseTransport):
    """Answers `POST .../chat/completions` from `script(messages, tools)`. Each request body is kept in `requests`
    and its headers in `headers`, so a test reads what the loop sent. Text streams in `chunk`-character pieces."""

    def __init__(self, script: Script, *, model: str = "scripted", chunk: int = 7) -> None:
        self.script = script
        self.model = model
        self.chunk = chunk
        self.requests: list[Json] = []
        self.headers: list[dict[str, str]] = []

    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        if request.method != "POST" or not request.url.path.endswith(COMPLETIONS):
            return httpx2.Response(404, json={"error": {"message": f"No scripted route {request.url.path}."}})
        body = cast(Json, json.loads(await request.aread()))
        self.requests.append(body)
        self.headers.append(dict(request.headers))
        messages = cast(list[Json], body.get("messages") or [])
        tools = cast(list[Json], body.get("tools") or [])
        answered = self.script(messages, tools)
        if isinstance(answered, Awaitable):
            answered = await answered
        reply = _reply(answered, tools)
        if reply.status != 200:
            return httpx2.Response(reply.status, json=reply.error or {})
        calls = _wire_calls(reply, len(messages))
        if body.get("stream"):
            return self._stream(reply, calls)
        message: dict[str, Any] = {"role": "assistant", "content": reply.text or None}
        if calls:
            message["tool_calls"] = calls
        return httpx2.Response(
            200,
            json={
                "id": "chatcmpl-scripted",
                "object": "chat.completion",
                "created": 0,
                "model": self.model,
                "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if calls else "stop"}],
                "usage": _usage(reply),
            },
        )

    def _chunk(self, delta: Json, finish: str | None = None) -> Json:
        return {
            "id": "chatcmpl-scripted",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": self.model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }

    def _stream(self, reply: Reply, calls: list[Json]) -> httpx2.Response:
        chunks: list[Json] = [self._chunk({"role": "assistant", "content": ""})]
        text = reply.text
        chunks += [self._chunk({"content": text[k : k + self.chunk]}) for k in range(0, len(text), self.chunk)]
        chunks += [self._chunk({"tool_calls": [{"index": i, **c}]}) for i, c in enumerate(calls)]
        chunks.append(self._chunk({}, "tool_calls" if calls else "stop"))
        chunks.append({**self._chunk({}), "choices": [], "usage": _usage(reply)})
        sse = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=sse.encode())


def last_user_text(messages: Sequence[Json]) -> str:
    """The text of the newest user message, or empty."""
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(
                    str(cast(Json, p).get("text") or "") for p in cast(list[Any], content) if isinstance(p, dict)
                )
    return ""


def trailing_tool_results(messages: Sequence[Json]) -> list[str]:
    """The tool results after the model's last message: what the model is answering, when it answers a tool call."""
    out: list[str] = []
    for m in reversed(messages):
        if m.get("role") != "tool":
            break
        out.append(str(m.get("content") or ""))
    return list(reversed(out))


def system_text(messages: Sequence[Json]) -> str:
    """The instructions and system prompts the model was given."""
    return " ".join(str(m.get("content") or "") for m in messages if m.get("role") in ("system", "developer"))


__all__ = [
    "Reply",
    "Script",
    "ScriptedModel",
    "Structured",
    "ToolCall",
    "last_user_text",
    "system_text",
    "tool_names",
    "trailing_tool_results",
]
