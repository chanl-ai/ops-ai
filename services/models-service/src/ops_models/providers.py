"""Provider connections a completion is forwarded to. `scripted` answers deterministically with no network, for tests
and use cases; `openai-compatible` forwards to the connection's base URL with the credential its `key_ref` names;
`azure-openai` forwards to an Azure OpenAI resource in Azure's own header and paths. `anthropic` connections can be
registered but are not served in this slice.

Both shapes carry tools: the request's `tools` reach the provider and its `tool_calls` come back, whole or as stream
deltas, in OpenAI's chunk shape.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol, cast
from urllib.parse import quote

import httpx

from .connection_settings import AZURE_OPENAI_V1


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


def _call_arguments(rest: str) -> dict[str, Any] | None:
    """The JSON object right after `call <tool>`; empty when nothing JSON-like follows, None when it does not parse to
    an object."""
    rest = rest.lstrip()
    if not rest.startswith(("{", "[")):
        return {}
    try:
        found, _ = json.JSONDecoder().raw_decode(rest)
    except ValueError:
        return None
    return cast(dict[str, Any], found) if isinstance(found, dict) else None


class ScriptedProvider:
    """Replies with a fixed sentence; token counts are word counts, so tests can predict cost. When the request offers
    tools and the last message is a user turn saying `call <tool>`, it calls that tool instead: with the JSON object
    written right after the name (`call github_list_issues {"owner": "acme"}`), else with no arguments. A `{` or `[`
    after the name that is not one JSON object is answered as text naming the problem, not called with nothing."""

    def _answer(self, model_id: str, body: dict[str, Any]) -> Completion:
        messages: list[dict[str, Any]] = list(body.get("messages") or [])
        prompt_tokens = _words(messages)
        tools: list[dict[str, Any]] = list(body.get("tools") or [])
        functions: list[dict[str, Any]] = [t.get("function") or {} for t in tools]
        offered = {str(f.get("name")) for f in functions}
        last = messages[-1] if messages else {}
        said = str(last.get("content") or "")
        wanted = _CALL.search(said) if last.get("role") == "user" else None
        if wanted and wanted.group(1) in offered:
            arguments = _call_arguments(said[wanted.end() :])
            if arguments is None:
                text = f"call {wanted.group(1)}: the arguments after its name must be one JSON object"
                return Completion(text, prompt_tokens, len(text.split()))
            call = {
                "id": "call_scripted_1",
                "type": "function",
                "function": {"name": wanted.group(1), "arguments": json.dumps(arguments)},
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
    """OpenAI's chat completions at `{base_url}/chat/completions`, the key as a bearer token."""

    def __init__(self, base_url: str, api_key: str | None, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = client or httpx.AsyncClient(timeout=60)

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _url(self, model_id: str) -> str:
        return f"{self.base_url}/chat/completions"

    def _answered(self, r: httpx.Response) -> None:
        """Raises when the answer is refused. Never quotes the body: a provider's 401 can echo part of the key."""
        if r.status_code >= 400:
            raise ProviderError(f"provider answered {r.status_code}")

    def _keep(self, chunk: dict[str, Any]) -> dict[str, Any] | None:
        """The chunk as callers get it, or None to drop it."""
        return chunk

    async def complete(self, model_id: str, body: dict[str, Any]) -> Completion:
        try:
            r = await self.client.post(
                self._url(model_id), json={**body, "model": model_id, "stream": False}, headers=self._headers
            )
        except httpx.HTTPError as e:
            # An unreachable endpoint is the provider's failure (502), not this service's (500).
            raise ProviderError(f"provider unreachable at {self.base_url}: {type(e).__name__}") from e
        self._answered(r)
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
            async with self.client.stream("POST", self._url(model_id), json=sent, headers=self._headers) as r:
                self._answered(r)
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
                    if (kept := self._keep(chunk)) is not None:
                        yield kept
        except httpx.HTTPError as e:
            raise ProviderError(f"provider unreachable at {self.base_url}: {type(e).__name__}") from e


# Azure's annotations, which no OpenAI client reads: dropped so callers see OpenAI's shape.
_AZURE_ANNOTATIONS = ("prompt_filter_results", "content_filter_results", "content_filter_offsets")


def region_key(region: str) -> str:
    """A region as both spellings compare: `Sweden Central` (Azure's header) and `swedencentral` (its id)."""
    return re.sub(r"[^a-z0-9]", "", region.lower())


def region_mismatch(observed: str | None, expected: str | None) -> str | None:
    """`answered from <observed>, expected <expected>` when Azure answered from another region than the connection
    names; None when they agree or either is unknown. The one rule the call log and the connection list both show."""
    if observed and expected and region_key(observed) != region_key(expected):
        return f"answered from {observed}, expected {expected}"
    return None


class AzureOpenAIProvider(OpenAICompatibleProvider):
    """Azure OpenAI: the key in the `api-key` header (Azure's deployment path refuses a bearer token), and
    `{endpoint}/openai/v1/chat/completions` with the deployment as `model` when `api_version` is `v1`, else
    `{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=<version>`. The alias's model id is the
    deployment. Every answer's `x-ms-region` header is recorded as `observed_region`; one that is not `region` is named
    by `region_mismatch` and the call goes through (owner, 2026-10-31: warn only until a real resource confirms the
    header)."""

    def __init__(
        self,
        endpoint: str,
        api_version: str,
        region: str | None,
        api_key: str | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(endpoint, api_key, client)
        self.api_version = api_version
        self.region = region
        self.observed_region: str | None = None

    @property
    def _headers(self) -> dict[str, str]:
        return {"api-key": self.api_key} if self.api_key else {}

    def _url(self, model_id: str) -> str:
        if self.api_version == AZURE_OPENAI_V1:
            return f"{self.base_url}/openai/v1/chat/completions"
        deployment = quote(model_id, safe="")
        return f"{self.base_url}/openai/deployments/{deployment}/chat/completions?api-version={self.api_version}"

    def _answered(self, r: httpx.Response) -> None:
        self.observed_region = r.headers.get("x-ms-region") or self.observed_region
        super()._answered(r)

    @property
    def region_mismatch(self) -> str | None:
        """`answered from <region>, expected <region>` when Azure answered from another region; None otherwise."""
        return region_mismatch(self.observed_region, self.region)

    def _keep(self, chunk: dict[str, Any]) -> dict[str, Any] | None:
        raw: list[dict[str, Any]] = chunk.get("choices") or []
        choices = [{k: v for k, v in c.items() if k not in _AZURE_ANNOTATIONS} for c in raw if "delta" in c]
        if not choices and not chunk.get("usage"):
            return None
        return {**{k: v for k, v in chunk.items() if k not in _AZURE_ANNOTATIONS}, "choices": choices}


def provider_for(
    connection: Mapping[str, Any] | Any, secrets: Mapping[str, str], client: httpx.AsyncClient | None = None
) -> Provider:
    kind = connection["type"]
    if kind == "scripted":
        return ScriptedProvider()
    key_ref = connection.get("key_ref")
    api_key = secrets.get(str(key_ref)) if key_ref else None
    if kind == "openai-compatible":
        return OpenAICompatibleProvider(str(connection["base_url"]), api_key, client)
    if kind == "azure-openai":
        version, region = str(connection["api_version"]), connection.get("region")
        return AzureOpenAIProvider(str(connection["base_url"]), version, region, api_key, client)
    raise ProviderError(f"provider type {kind} is not served yet")
