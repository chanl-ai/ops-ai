"""Provider connections a completion is forwarded to. `scripted` answers deterministically with no network, for tests
and use cases; `openai-compatible` forwards to the connection's base URL with the credential its `key_ref` names.
`anthropic` connections can be registered but are not served in this slice.

Both shapes carry tools: the request's `tools` reach the provider and its `tool_calls` come back, whole or as stream
deltas, in OpenAI's chunk shape.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


@dataclass(frozen=True)
class Completion:
    text: str | None
    input_tokens: int
    output_tokens: int
    tool_calls: list[dict[str, Any]] = field(default_factory=lambda: [])

    @property
    def finish_reason(self) -> str:
        return "tool_calls" if self.tool_calls else "stop"


@dataclass
class StreamUsage:
    """Filled while a stream is read; final once it ends."""

    input_tokens: int = 0
    output_tokens: int = 0


class ProviderError(Exception):
    pass


class Provider(Protocol):
    async def complete(self, model_id: str, body: dict[str, Any]) -> Completion: ...

    def stream(self, model_id: str, body: dict[str, Any], usage: StreamUsage) -> AsyncIterator[dict[str, Any]]:
        """OpenAI `chat.completion.chunk` dicts; `usage` holds the totals once the iterator is exhausted."""
        ...


def _words(messages: list[dict[str, Any]]) -> int:
    return sum(len(str(m.get("content") or "").split()) for m in messages)


_CALL = re.compile(r"\bcall (\w+)")


class ScriptedProvider:
    """Replies with a fixed sentence; token counts are word counts, so tests can predict cost. When the request offers
    tools and the last message is a user turn saying `call <tool>`, it calls that tool with empty arguments instead."""

    def _answer(self, model_id: str, body: dict[str, Any]) -> Completion:
        messages: list[dict[str, Any]] = list(body.get("messages") or [])
        prompt_tokens = _words(messages)
        tools: list[dict[str, Any]] = list(body.get("tools") or [])
        functions: list[dict[str, Any]] = [t.get("function") or {} for t in tools]
        offered = {str(f.get("name")) for f in functions}
        last = messages[-1] if messages else {}
        wanted = _CALL.search(str(last.get("content") or "")) if last.get("role") == "user" else None
        if wanted and wanted.group(1) in offered:
            call = {
                "id": "call_scripted_1",
                "type": "function",
                "function": {"name": wanted.group(1), "arguments": "{}"},
            }
            return Completion(None, prompt_tokens, 1, [call])
        text = f"scripted reply from {model_id}"
        return Completion(text, prompt_tokens, len(text.split()))

    async def complete(self, model_id: str, body: dict[str, Any]) -> Completion:
        return self._answer(model_id, body)

    async def stream(self, model_id: str, body: dict[str, Any], usage: StreamUsage) -> AsyncIterator[dict[str, Any]]:
        done = self._answer(model_id, body)
        usage.input_tokens, usage.output_tokens = done.input_tokens, done.output_tokens
        for chunk in completion_chunks(done):
            yield chunk


def completion_chunks(done: Completion) -> Iterator[dict[str, Any]]:
    """A finished completion as OpenAI `chat.completion.chunk` dicts: a role delta, the text word by word or each tool
    call whole, the finish reason, then the usage-only chunk `stream_options.include_usage` asks for."""
    yield _chunk({"role": "assistant", "content": ""})
    if done.tool_calls:
        for i, call in enumerate(done.tool_calls):
            yield _chunk({"tool_calls": [{"index": i, **call}]})
    else:
        for i, word in enumerate((done.text or "").split(" ")):
            yield _chunk({"content": word if i == 0 else " " + word})
    yield _chunk({}, finish_reason=done.finish_reason)
    # OpenAI's last chunk under include_usage: no choices, the totals. Callers meter from it.
    totals = {"prompt_tokens": done.input_tokens, "completion_tokens": done.output_tokens}
    yield {
        "object": "chat.completion.chunk",
        "choices": [],
        "usage": {**totals, "total_tokens": sum(totals.values())},
    }


def _chunk(delta: dict[str, Any], finish_reason: str | None = None) -> dict[str, Any]:
    return {
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


class OpenAICompatibleProvider:
    def __init__(self, base_url: str, api_key: str | None, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = client or httpx.AsyncClient(timeout=60)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    async def complete(self, model_id: str, body: dict[str, Any]) -> Completion:
        try:
            r = await self.client.post(
                f"{self.base_url}/chat/completions",
                json={**body, "model": model_id, "stream": False},
                headers=self._headers,
            )
        except httpx.HTTPError as e:
            # An unreachable endpoint is the provider's failure (502), not this service's (500).
            raise ProviderError(f"provider unreachable at {self.base_url}: {type(e).__name__}") from e
        if r.status_code >= 400:
            raise ProviderError(f"provider answered {r.status_code}")
        data: dict[str, Any] = r.json()
        usage: dict[str, Any] = data.get("usage") or {}
        choices: list[dict[str, Any]] = data.get("choices") or [{}]
        message: dict[str, Any] = choices[0].get("message") or {}
        return Completion(
            message.get("content"),
            int(usage.get("prompt_tokens", 0)),
            int(usage.get("completion_tokens", 0)),
            list(message.get("tool_calls") or []),
        )

    async def stream(self, model_id: str, body: dict[str, Any], usage: StreamUsage) -> AsyncIterator[dict[str, Any]]:
        # include_usage puts the totals on a last chunk with no choices; metering needs them.
        sent = {**body, "model": model_id, "stream": True, "stream_options": {"include_usage": True}}
        try:
            async with self.client.stream(
                "POST", f"{self.base_url}/chat/completions", json=sent, headers=self._headers
            ) as r:
                if r.status_code >= 400:
                    raise ProviderError(f"provider answered {r.status_code}")
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    chunk: dict[str, Any] = json.loads(data)
                    if u := chunk.get("usage"):
                        usage.input_tokens = int(u.get("prompt_tokens", 0))
                        usage.output_tokens = int(u.get("completion_tokens", 0))
                    yield chunk
        except httpx.HTTPError as e:
            raise ProviderError(f"provider unreachable at {self.base_url}: {type(e).__name__}") from e


def provider_for(
    connection: Mapping[str, Any] | Any, secrets: Mapping[str, str], client: httpx.AsyncClient | None = None
) -> Provider:
    kind = connection["type"]
    if kind == "scripted":
        return ScriptedProvider()
    if kind == "openai-compatible":
        key_ref = connection.get("key_ref")
        api_key = secrets.get(str(key_ref)) if key_ref else None
        return OpenAICompatibleProvider(str(connection["base_url"]), api_key, client)
    raise ProviderError(f"provider type {kind} is not served yet")
