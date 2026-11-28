"""The adapters a completion is forwarded through, registered by name in `ADAPTERS`; each provider type in the
registry (`registry.py`) names one. `scripted` answers deterministically with no network, for tests and use cases;
`openai-compatible` forwards to the connection's base URL (or its type's, as OpenAI, Anthropic and Google Gemini
serve OpenAI's chat API) with the credential its `key_ref` names as a bearer token; `azure-openai` forwards to an
Azure OpenAI resource in Azure's own header and paths; `bedrock` forwards to Amazon Bedrock's OpenAI-compatible chat
API, each request signed with the connection's access key pair. Each connection also embeds text for an alias of kind
embedding.

Both shapes carry tools: the request's `tools` reach the provider and its `tool_calls` come back, whole or as stream
deltas, in OpenAI's chunk shape.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast, get_args
from urllib.parse import quote

import httpx
from pydantic import TypeAdapter

from ops_service_kit.http import Json, JsonList, JsonValue
from ops_service_kit.names import slugify
from ops_service_kit.narrow import Malformed, a_list, an_object, json_list, json_object
from ops_service_kit.scripted_vectors import SCRIPTED_WIDTH, scripted_vector

from .connection_settings import AZURE_OPENAI_V1
from .registry import ProviderEntry, Registry
from .schemas import ChatChunk, ChatUsage, ChunkChoice, ChunkDelta
from .sigv4 import signed_headers
from .store.aliases import ServingAlias

# How a reply ended, in the words OpenAI's format names: whole, a call for tools, cut at its length limit, stopped by
# the provider's content filter. A caller reads a reply that holds no answer from these.
Finish = Literal["stop", "tool_calls", "length", "content_filter"]
FINISHES: frozenset[str] = frozenset(get_args(Finish))


@dataclass(frozen=True)
class Completion:
    text: str | None
    input_tokens: int
    output_tokens: int
    # The calls as the model wrote them (OpenAI's `tool_calls`); the reply keeps only the keys OpenAI's format names.
    tool_calls: list[dict[str, Any]] = field(default_factory=lambda: [])
    # The provider's own word for how the reply ended (None when it sent none).
    ended: str | None = None
    # The model's words when it declined (OpenAI's `message.refusal`).
    refusal: str | None = None

    @property
    def finish_reason(self) -> Finish:
        """The provider's word when OpenAI's format names it, else read from the reply's content, so a provider's own
        word never fails a whole reply."""
        if self.ended in FINISHES:
            return cast(Finish, self.ended)
        return "tool_calls" if self.tool_calls else "stop"


@dataclass
class StreamUsage:
    """Filled while a stream is read; final once it ends."""

    input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class Embedded:
    vectors: list[list[float]]
    input_tokens: int


# How models-service answers each way a provider can fail: its status, the sentence that says what happened, and what to
# do next. The one place a provider failure is classified; a caller reads the code, a person reads the message.
ADMIN_FIX = "An account admin checks the connection and its key on Settings > Model providers."
PROVIDER_FAILURES: dict[str, tuple[int, str]] = {
    "provider_unreachable": (502, f"The model provider could not be reached. {ADMIN_FIX}"),
    "provider_timeout": (504, "The model provider did not answer in time. Retry in a moment."),
    "provider_auth_failed": (502, f"The model provider refused the account's key. {ADMIN_FIX}"),
    "provider_rate_limited": (
        429,
        "The model provider is limiting calls on the account's key. Wait a minute and retry; if it keeps happening, an "
        "account admin raises the limit with the provider.",
    ),
    "provider_bad_request": (
        502,
        "The model provider refused the request: the model or deployment name, or a setting, may be wrong. "
        + ADMIN_FIX,
    ),
    "provider_error": (502, "The model provider failed to answer. Retry in a moment."),
}


class ProviderError(Exception):
    """A provider that failed, as models-service answers it: `code` from PROVIDER_FAILURES, its `status` and message,
    and the provider's own Retry-After. The message never quotes the provider's body: a 401 can echo part of the key."""

    def __init__(self, code: str = "provider_error", *, why: str = "", retry_after: str | None = None) -> None:
        self.code = code
        self.status, self.message = PROVIDER_FAILURES[code]
        self.retry_after = retry_after
        # `why` is for the service's own log line, never the answer.
        super().__init__(why or self.message)


def answered(status: int) -> str:
    """The code for a provider's HTTP answer of `status` (400 or more)."""
    if status in (401, 403):
        return "provider_auth_failed"
    if status == 429:
        return "provider_rate_limited"
    return "provider_error" if status >= 500 else "provider_bad_request"


def refusal_reason(r: httpx.Response) -> str:
    """A refusal body's OpenAI-style `error.code`, `error.param` and the first 160 characters of `error.message`, for
    the log; a body in any other shape gives its first 160 characters."""
    try:
        body = r.json()
    except ValueError:
        return r.text[:160]
    error = cast(dict[str, object], body).get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return json.dumps(body)[:160]
    fields = cast(dict[str, object], error)
    return f"code={fields.get('code')} param={fields.get('param')} message={str(fields.get('message') or '')[:160]}"


def unreached(e: httpx.HTTPError) -> ProviderError:
    """A request that got no answer: a timeout, or a provider that could not be reached at all."""
    code = "provider_timeout" if isinstance(e, httpx.TimeoutException) else "provider_unreachable"
    return ProviderError(code, why=f"{code}: {type(e).__name__}")


class Provider(Protocol):
    async def complete(self, model_id: str, body: Json) -> Completion: ...

    async def embed(self, model_id: str, inputs: list[str], dimensions: int | None) -> Embedded:
        """One vector per input, in order, `dimensions` wide when the caller names a width."""
        ...

    def stream(self, model_id: str, body: Json, usage: StreamUsage) -> AsyncIterator[Json]:
        """OpenAI `chat.completion.chunk` objects; `usage` holds the totals once the iterator is exhausted."""
        ...


def _words(messages: JsonList) -> int:
    return sum(len(str(json_object(m).get("content") or "").split()) for m in messages)


def _count(value: JsonValue) -> int:
    """A provider's token count or index as `int()` reads it (2, 2.0 and "2" alike). Anything else is `Malformed`: a
    count that is billed is never read as 0."""
    if isinstance(value, int | float | str):
        return int(value)
    raise Malformed(f"{value!r} is not a count")


def malformed(e: ValueError) -> ProviderError:
    """A provider answer of the wrong shape, failed as the provider's error: the call is logged and not billed."""
    return ProviderError(why=f"provider answer malformed: {e}")


# A provider's vector, checked: a missing or non-numeric one fails the call as it did before it was checked.
_VECTOR: TypeAdapter[list[float]] = TypeAdapter(list[float])


_CALL = re.compile(r"\bcall (\w+)")


def _call_arguments(rest: str) -> Json | None:
    """The JSON object right after `call <tool>`; empty when nothing JSON-like follows, None when it does not parse to
    an object."""
    rest = rest.lstrip()
    if not rest.startswith(("{", "[")):
        return {}
    try:
        found: object = json.JSONDecoder().raw_decode(rest)[0]
    except ValueError:
        return None
    parsed = json_object(found)
    return parsed if isinstance(found, dict) else None


class ScriptedProvider:
    """Replies with a fixed sentence; token counts are word counts, so tests can predict cost. When the request offers
    tools and the last message is a user turn saying `call <tool>`, it calls that tool instead: with the JSON object
    written right after the name (`call github_list_issues {"owner": "acme"}`), else with no arguments. A `{` or `[`
    after the name that is not one JSON object is answered as text naming the problem, not called with nothing."""

    def _answer(self, model_id: str, body: Json) -> Completion:
        messages = json_list(body.get("messages"))
        prompt_tokens = _words(messages)
        tools = [an_object(t, "tool") for t in json_list(body.get("tools"))]
        functions = [an_object(f, "tool function") if (f := t.get("function")) else {} for t in tools]
        offered = {str(f.get("name")) for f in functions}
        last = json_object(messages[-1]) if messages else {}
        said = str(last.get("content") or "")
        wanted = _CALL.search(said) if last.get("role") == "user" else None
        if wanted and wanted.group(1) in offered:
            arguments = _call_arguments(said[wanted.end() :])
            if arguments is None:
                text = f"call {wanted.group(1)}: the arguments after its name must be one JSON object"
                return Completion(text, prompt_tokens, len(text.split()))
            call: Json = {
                "id": "call_scripted_1",
                "type": "function",
                "function": {"name": wanted.group(1), "arguments": json.dumps(arguments)},
            }
            return Completion(None, prompt_tokens, 1, [call])
        text = f"scripted reply from {model_id}"
        return Completion(text, prompt_tokens, len(text.split()))

    async def complete(self, model_id: str, body: Json) -> Completion:
        return self._answer(model_id, body)

    async def embed(self, model_id: str, inputs: list[str], dimensions: int | None) -> Embedded:
        width = dimensions or SCRIPTED_WIDTH
        return Embedded([scripted_vector(t, width) for t in inputs], sum(len(t.split()) for t in inputs))

    async def stream(self, model_id: str, body: Json, usage: StreamUsage) -> AsyncIterator[Json]:
        done = self._answer(model_id, body)
        usage.input_tokens, usage.output_tokens = done.input_tokens, done.output_tokens
        for chunk in completion_chunks(done):
            yield chunk


def completion_chunks(done: Completion) -> Iterator[dict[str, Any]]:
    """A finished completion as OpenAI `chat.completion.chunk` objects: a role delta, the text word by word or each
    tool call whole, the finish reason, then the usage-only chunk `stream_options.include_usage` asks for."""
    yield _chunk(ChunkDelta(role="assistant", content=""))
    if done.tool_calls:
        for i, call in enumerate(done.tool_calls):
            yield _chunk(ChunkDelta(tool_calls=[{"index": i, **call}]))
    else:
        for i, word in enumerate((done.text or "").split(" ")):
            yield _chunk(ChunkDelta(content=word if i == 0 else " " + word))
    yield _chunk(ChunkDelta(), finish_reason=done.finish_reason)
    # OpenAI's last chunk under include_usage: no choices, the totals. Callers meter from it.
    totals = ChatUsage(
        prompt_tokens=done.input_tokens,
        completion_tokens=done.output_tokens,
        total_tokens=done.input_tokens + done.output_tokens,
    )
    yield ChatChunk(object="chat.completion.chunk", choices=[], usage=totals).model_dump(exclude_unset=True)


def _chunk(delta: ChunkDelta, finish_reason: Finish | None = None) -> Json:
    choice = ChunkChoice(index=0, delta=delta, finish_reason=finish_reason)
    # `exclude_unset` keeps the wire shape: a delta names only what it adds, and a chunk has no `usage` key.
    return ChatChunk(object="chat.completion.chunk", choices=[choice]).model_dump(exclude_unset=True)


def _usage(answer: Json) -> Json:
    """The answer's `usage`; empty when it is absent or null, as an answer without totals is metered at 0."""
    found = answer.get("usage")
    return an_object(found, "usage") if found else {}


def _completion(answer: JsonValue) -> Completion:
    """A chat completion answer read as `Completion`. Text content only: content of another kind (a list of parts)
    is `Malformed`, as the reply could not carry it."""
    data = an_object(answer, "answer")
    usage = _usage(data)
    listed = data.get("choices")
    choices: JsonList = a_list(listed, "choices") if listed else [{}]
    found = an_object(choices[0], "choice").get("message")
    message = an_object(found, "message") if found else {}
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise Malformed("message content is not text")
    calls = message.get("tool_calls")
    ended, refusal = an_object(choices[0], "choice").get("finish_reason"), message.get("refusal")
    return Completion(
        content,
        _count(usage.get("prompt_tokens", 0)),
        _count(usage.get("completion_tokens", 0)),
        [an_object(c, "tool call") for c in (a_list(calls, "tool_calls") if calls else [])],
        ended=ended if isinstance(ended, str) else None,
        refusal=refusal if isinstance(refusal, str) and refusal else None,
    )


class OpenAICompatibleProvider:
    """OpenAI's chat completions at `{base_url}/chat/completions`, the key as a bearer token."""

    def __init__(self, base_url: str, api_key: str | None, client: httpx.AsyncClient) -> None:
        # The app's one provider client (`create_models_app`), opened and closed with the app.
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = client

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    def _signed(self, method: str, url: str, payload: bytes) -> dict[str, str]:
        """The headers one request goes with; an adapter that signs each request (Bedrock) reads its body here."""
        return {**self._headers, "content-type": "application/json"}

    def _url(self, model_id: str) -> str:
        return f"{self.base_url}/chat/completions"

    def _embeddings_url(self, model_id: str) -> str:
        return f"{self.base_url}/embeddings"

    async def _answered(self, r: httpx.Response) -> None:
        """Raises when the answer is refused. A 401 or 403 body is never read, since it can echo part of the key; any
        other refusal's error code, parameter and the start of its message go on the service's log line."""
        if r.status_code >= 400:
            code = answered(r.status_code)
            why = f"provider answered {r.status_code}"
            if code != "provider_auth_failed":
                await r.aread()
                why = f"{why}: {refusal_reason(r)}"
            raise ProviderError(code, why=why, retry_after=r.headers.get("retry-after"))

    def _keep(self, chunk: Json) -> Json | None:
        """The chunk as callers get it, or None to drop it."""
        return chunk

    async def complete(self, model_id: str, body: Json) -> Completion:
        url, payload = self._url(model_id), json.dumps({**body, "model": model_id, "stream": False}).encode()
        try:
            r = await self.client.post(url, content=payload, headers=self._signed("POST", url, payload))
        except httpx.HTTPError as e:
            # An unreachable endpoint is the provider's failure (502), not this service's (500).
            raise unreached(e) from e
        await self._answered(r)
        try:
            return _completion(r.json())
        except ValueError as e:
            raise malformed(e) from e

    async def embed(self, model_id: str, inputs: list[str], dimensions: int | None) -> Embedded:
        body: Json = {"model": model_id, "input": list[JsonValue](inputs)}
        if dimensions is not None:
            body["dimensions"] = dimensions
        url, payload = self._embeddings_url(model_id), json.dumps(body).encode()
        try:
            r = await self.client.post(url, content=payload, headers=self._signed("POST", url, payload))
        except httpx.HTTPError as e:
            raise unreached(e) from e
        await self._answered(r)
        try:
            data = an_object(r.json(), "answer")
            listed = data.get("data")
            rows = sorted(
                (an_object(d, "vector row") for d in (a_list(listed, "data") if listed else [])),
                key=lambda d: _count(d.get("index", 0)),
            )
            usage = _usage(data)
            vectors = [_VECTOR.validate_python(d["embedding"]) for d in rows]
            used = _count(usage.get("prompt_tokens", 0))
        except (ValueError, KeyError) as e:
            raise ProviderError(why=f"provider answer malformed: {e!r}") from e
        if len(rows) != len(inputs):
            raise ProviderError(why=f"provider returned {len(rows)} vectors for {len(inputs)} inputs")
        return Embedded(vectors, used)

    async def stream(self, model_id: str, body: Json, usage: StreamUsage) -> AsyncIterator[Json]:
        # include_usage puts the totals on a last chunk with no choices; metering needs them.
        sent = {**body, "model": model_id, "stream": True, "stream_options": {"include_usage": True}}
        url, payload = self._url(model_id), json.dumps(sent).encode()
        try:
            headers = self._signed("POST", url, payload)
            async with self.client.stream("POST", url, content=payload, headers=headers) as r:
                await self._answered(r)
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    # Passed on as parsed, never through a model: a field the provider adds reaches the client.
                    try:
                        chunk = an_object(json.loads(data), "stream chunk")
                        if u := _usage(chunk):
                            usage.input_tokens = _count(u.get("prompt_tokens", 0))
                            usage.output_tokens = _count(u.get("completion_tokens", 0))
                        kept = self._keep(chunk)
                    except ValueError as e:
                        raise malformed(e) from e
                    if kept is not None:
                        yield kept
        except httpx.HTTPError as e:
            raise unreached(e) from e


# Azure's annotations, which no OpenAI client reads: dropped so callers see OpenAI's shape.
_AZURE_ANNOTATIONS = ("prompt_filter_results", "content_filter_results", "content_filter_offsets")


def region_key(region: str) -> str:
    """A region as both spellings compare: `Sweden Central` (Azure's header) and `swedencentral` (its id)."""
    return slugify(region, width=200, sep="")


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
    by `region_mismatch` and the call goes through (warn only until a real resource confirms the
    header)."""

    def __init__(
        self,
        endpoint: str,
        api_version: str,
        region: str | None,
        api_key: str | None,
        client: httpx.AsyncClient,
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

    def _embeddings_url(self, model_id: str) -> str:
        if self.api_version == AZURE_OPENAI_V1:
            return f"{self.base_url}/openai/v1/embeddings"
        deployment = quote(model_id, safe="")
        return f"{self.base_url}/openai/deployments/{deployment}/embeddings?api-version={self.api_version}"

    async def _answered(self, r: httpx.Response) -> None:
        self.observed_region = r.headers.get("x-ms-region") or self.observed_region
        await super()._answered(r)

    @property
    def region_mismatch(self) -> str | None:
        """`answered from <region>, expected <region>` when Azure answered from another region; None otherwise."""
        return region_mismatch(self.observed_region, self.region)

    def _keep(self, chunk: Json) -> Json | None:
        listed = chunk.get("choices")
        raw = [an_object(c, "choice") for c in (a_list(listed, "choices") if listed else [])]
        choices: JsonList = [{k: v for k, v in c.items() if k not in _AZURE_ANNOTATIONS} for c in raw if "delta" in c]
        if not choices and not chunk.get("usage"):
            return None
        return {**{k: v for k, v in chunk.items() if k not in _AZURE_ANNOTATIONS}, "choices": choices}


class BedrockProvider(OpenAICompatibleProvider):
    """Amazon Bedrock's OpenAI-compatible chat API at `{base_url}/chat/completions`, each request signed (SigV4, service
    `bedrock`) with the connection's access key pair, saved as one provider key holding `accessKeyId` and
    `secretAccessKey`. **Unverified** against a real account."""

    def __init__(self, base_url: str, region: str, secret: str | None, client: httpx.AsyncClient) -> None:
        super().__init__(base_url, None, client)
        self.region = region
        pair = bedrock_pair(secret)
        self.access_key, self.secret_key = pair if pair else ("", "")

    def _signed(self, method: str, url: str, payload: bytes) -> dict[str, str]:
        if not self.access_key:
            raise ProviderError("provider_auth_failed", why="bedrock connection has no saved access key pair")
        signed = signed_headers(
            method,
            url,
            payload,
            access_key=self.access_key,
            secret_key=self.secret_key,
            region=self.region,
            service="bedrock",
        )
        return {**signed, "content-type": "application/json"}


def bedrock_pair(secret: str | None) -> tuple[str, str] | None:
    """(access key id, secret access key) from a saved Bedrock key; None when it is not that JSON object."""
    try:
        held = json_object(json.loads(secret or ""))
    except ValueError:
        return None
    key_id, key = held.get("accessKeyId"), held.get("secretAccessKey")
    return (key_id, key) if isinstance(key_id, str) and isinstance(key, str) and key_id and key else None


class Adapter(Protocol):
    def __call__(
        self, entry: ProviderEntry, connection: ServingAlias, api_key: str | None, client: httpx.AsyncClient
    ) -> Provider: ...


def _unserved(why: str) -> ProviderError:
    return ProviderError("provider_bad_request", why=why)


def _openai_compatible(
    entry: ProviderEntry, connection: ServingAlias, api_key: str | None, client: httpx.AsyncClient
) -> Provider:
    base = entry.base_for(connection.base_url, connection.region)
    if not base:
        raise _unserved(f"{entry.id} connection has no base URL")
    return OpenAICompatibleProvider(base, api_key, client)


def _azure(entry: ProviderEntry, connection: ServingAlias, api_key: str | None, client: httpx.AsyncClient) -> Provider:
    version, region = str(connection.api_version), connection.region
    return AzureOpenAIProvider(str(connection.base_url), version, region, api_key, client)


def _bedrock(
    entry: ProviderEntry, connection: ServingAlias, api_key: str | None, client: httpx.AsyncClient
) -> Provider:
    base = entry.base_for(connection.base_url, connection.region)
    if not base or not connection.region:
        raise _unserved("bedrock connection has no region")
    return BedrockProvider(base, connection.region, api_key, client)


def _scripted(
    entry: ProviderEntry, connection: ServingAlias, api_key: str | None, client: httpx.AsyncClient
) -> Provider:
    return ScriptedProvider()


# Every adapter a registry entry may name. A new provider that speaks one of these APIs is a registry entry only.
ADAPTERS: dict[str, Adapter] = {
    "openai-compatible": _openai_compatible,
    "azure-openai": _azure,
    "bedrock": _bedrock,
    "scripted": _scripted,
}


def provider_for(
    connection: ServingAlias, secrets: Mapping[str, str], client: httpx.AsyncClient, registry: Registry
) -> Provider:
    entry = registry.get(connection.type)
    if entry is None:
        raise _unserved(f"provider type {connection.type} is not in the registry")
    key_ref = connection.key_ref
    api_key = secrets.get(key_ref) if key_ref else None
    return ADAPTERS[entry.adapter](entry, connection, api_key, client)
