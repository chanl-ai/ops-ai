"""The one client for a model call made by a service that is not an agent. The service holds its own model key (its
budget line in models-service, never a provider credential) and every call goes through models-service on an alias:

- `ModelCalls.structured`: a system and a user message, read back as the `final_result` function's arguments, the
  form the agent kernel asks structured output in;
- `ModelCalls.embed`: vectors for a batch of texts from an alias of kind embedding, with the tokens spent;
- `IngestModel.complete`: one prompt answered as text, for ingestion's AI steps, which run in a worker thread
  (`ops_ingest.ModelClient`).

A refusal keeps models-service's own code (`key_budget_exhausted`, `rate_limited`, `sensitivity_not_cleared`,
`alias_not_found`, ...) on `ModelCallError`, so a caller decides from the code rather than from the message, and an
answer in another shape is `models_answer_unreadable`. `Usage` collects what a caller's calls spent. No other module
posts to models-service's model routes (`ops_service_kit.standards`, rule SC1)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict, cast

import httpx

# The alias a service's structured calls use while models-service has no alias of the service's own name.
FALLBACK_ALIAS = "default"
# Codes for a call that never reached models-service, or whose answer could not be read.
UNREACHABLE = "models_unreachable"
UNREADABLE = "models_answer_unreadable"
TIMEOUT = "models_timeout"
# A reply that ended with no answer to use, each its own code so a caller says why and saves nothing: cut at the
# output limit, declined by the model, stopped by the provider's content filter, or holding nothing.
CUT_OFF = "reply_cut_off"
DECLINED = "reply_declined"
FILTERED = "reply_filtered"
EMPTY = "reply_empty"
# Every such ending: a caller that can go on without the answer (skip one piece, send a file to a person) catches these
# and still stops on an outage.
ENDINGS = frozenset({CUT_OFF, DECLINED, FILTERED, EMPTY})
# How much of a model's refusal an error keeps.
REFUSAL_CHARS = 300
# models-service's model routes; only this client posts to them (rule SC1, `standards.check_model_calls`).
CHAT_ROUTE = "/v1/models/chat/completions"
EMBED_ROUTE = "/v1/models/embeddings"


class ModelCallError(Exception):
    """models-service could not be reached, or refused the call with `code` and HTTP `status` (0 when unreached);
    `alias` is the alias that refused it, when one did."""

    def __init__(
        self,
        message: str,
        *,
        code: str = UNREACHABLE,
        status: int = 0,
        alias: str | None = None,
        refusal: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.alias = alias
        # The model's own words when it declined (`reply_declined`), cut to REFUSAL_CHARS.
        self.refusal = refusal


def _unreached(e: httpx.HTTPError) -> ModelCallError:
    """A call that got no answer from models-service: too late is told apart from not reached."""
    if isinstance(e, httpx.TimeoutException):
        return ModelCallError(f"models-service did not answer in time: {e!r}", code=TIMEOUT)
    return ModelCallError(f"models-service could not be reached: {e}")


def _ending(message: _Message, finish: object, *, answered: bool) -> ModelCallError | None:
    """Why a reply that models-service billed holds no answer to use, or None. `answered` is whether it carries the
    asked-for tool call or text. The provider's word for how it ended wins: a cut reply may still carry a call whose
    arguments stop partway."""
    said = message.get("refusal")
    if isinstance(said, str) and said.strip():
        words = said.strip()[:REFUSAL_CHARS]
        return ModelCallError(f"the model declined: {words}", code=DECLINED, refusal=words)
    if finish == "length":
        return ModelCallError("the model's reply was cut off at its output limit", code=CUT_OFF)
    if finish == "content_filter":
        return ModelCallError("the provider's content filter stopped the model's reply", code=FILTERED)
    if not answered:
        return ModelCallError("the model's reply held no answer", code=EMPTY)
    return None


@dataclass(frozen=True)
class Embedded:
    """One vector per text, in the order sent, the input tokens models-service charged for them, and the model that
    made them (its provider and model id): an alias can be pointed at another model, and vectors of two models are not
    comparable."""

    vectors: list[list[float]]
    input_tokens: int
    model: str = ""


@dataclass
class Usage:
    """What a caller's calls spent, as models-service billed them: each call it is passed to adds its count and tokens,
    so one record covers a first ask and its re-ask."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    # The alias that answered the latest call: a structured call falls back to `default` when its own is not bound.
    alias: str | None = None


class _Error(TypedDict, total=False):
    code: str
    message: str


class _Envelope(TypedDict, total=False):
    error: _Error


class _Function(TypedDict):
    arguments: str


class _ToolCall(TypedDict):
    function: _Function


class _Message(TypedDict, total=False):
    content: str | None
    tool_calls: list[_ToolCall] | None
    refusal: str | None


class _Choice(TypedDict):
    message: _Message
    finish_reason: NotRequired[str | None]


class _Counted(TypedDict, total=False):
    prompt_tokens: int
    completion_tokens: int


class _ChatReply(TypedDict):
    """models-service's chat completion, as far as this client reads it."""

    choices: list[_Choice]
    usage: NotRequired[_Counted | None]


class _Vector(TypedDict):
    index: int
    embedding: list[float]


class _EmbeddingsReply(TypedDict):
    data: list[_Vector]
    model: str
    usage: NotRequired[_Counted | None]


def _headers(key: str, tenant: str, step: str, sensitivity: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {key}",
        "X-Step-Id": step,
        "X-Tenant-Id": tenant,
        "X-Data-Sensitivity": sensitivity,
    }


def refusal(r: httpx.Response) -> ModelCallError:
    """models-service's refusal as an error carrying its code; a body that is not its envelope keeps the status."""
    try:
        error = cast(_Envelope, r.json()).get("error") or _Error()
    except (ValueError, AttributeError):
        error = _Error()
    code = str(error.get("code") or f"http_{r.status_code}")
    message = str(error.get("message") or r.text[:300])
    return ModelCallError(f"models-service answered {r.status_code} {code}: {message}", code=code, status=r.status_code)


def _chat_body(alias: str, messages: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"model": alias, "messages": messages, **extra}


def _structured_answer(r: httpx.Response, alias: str, usage: Usage | None) -> Any:
    try:
        data = cast(_ChatReply, r.json())
        choice = data["choices"][0]
        message = choice["message"]
        calls = message.get("tool_calls") or []
        raw = calls[0]["function"]["arguments"] if calls else message.get("content")
        counted = data.get("usage") or _Counted()
        tokens = (int(counted.get("prompt_tokens") or 0), int(counted.get("completion_tokens") or 0))
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
        raise ModelCallError(f"models-service's answer could not be read: {e!r}", code=UNREADABLE) from e
    # Counted before an ending is refused: models-service billed the reply either way.
    if usage is not None:
        usage.calls += 1
        usage.input_tokens += tokens[0]
        usage.output_tokens += tokens[1]
        usage.alias = alias
    answered = isinstance(raw, str) and bool(raw.strip())
    if (ended := _ending(message, choice.get("finish_reason"), answered=answered)) is not None:
        ended.alias = alias
        raise ended
    try:
        return json.loads(raw) if isinstance(raw, str) else {}
    except json.JSONDecodeError:
        return {}


def _embedded(r: httpx.Response, sent: int) -> Embedded:
    try:
        data = cast(_EmbeddingsReply, r.json())
        rows = sorted(data["data"], key=lambda d: int(d["index"]))
        vectors = [[float(x) for x in d["embedding"]] for d in rows]
        tokens = int((data.get("usage") or _Counted()).get("prompt_tokens", 0))
        model = cast(object, data["model"])
        if not isinstance(model, str) or not model:
            raise TypeError("no model named the vectors")
    except (ValueError, KeyError, TypeError) as e:
        raise ModelCallError(f"models-service's embeddings answer could not be read: {e}", code=UNREADABLE) from e
    if len(vectors) != sent:
        raise ModelCallError(f"models-service returned {len(vectors)} vectors for {sent} texts", code=UNREADABLE)
    return Embedded(vectors, tokens, model)


@dataclass
class ModelCalls:
    http: httpx.AsyncClient
    key: str
    alias: str = FALLBACK_ALIAS

    async def structured(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        tenant: str,
        step: str,
        sensitivity: str = "internal",
        run: str | None = None,
        parts: Sequence[dict[str, Any]] = (),
        usage: Usage | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        """The answer's arguments; {} when the model answered with something unreadable, which fails the caller's own
        schema check rather than raising. `parts` go after the user text in its message (a page image's
        `image_url`), `run` is the X-Run-Id the call is logged and capped under, and `usage` is added to once the call
        is answered."""
        content: str | list[dict[str, Any]] = [{"type": "text", "text": user}, *parts] if parts else user
        messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
        tools = [{"type": "function", "function": {"name": "final_result", "parameters": schema}}]
        headers = {**_headers(self.key, tenant, step, sensitivity), **({"X-Run-Id": run} if run else {})}
        limit = {"max_completion_tokens": max_tokens} if max_tokens is not None else {}
        for name in dict.fromkeys((self.alias, FALLBACK_ALIAS)):
            try:
                r = await self.http.post(
                    CHAT_ROUTE,
                    headers=headers,
                    json=_chat_body(name, messages, tools=tools, tool_choice="required", **limit),
                )
            except httpx.HTTPError as e:
                raise _unreached(e) from e
            if r.status_code == 404 and "alias_not_found" in r.text and name != FALLBACK_ALIAS:
                continue
            if r.status_code >= 400:
                refused = refusal(r)
                refused.alias = name
                raise refused
            return _structured_answer(r, name, usage)
        raise ModelCallError(f"models-service has neither {self.alias} nor {FALLBACK_ALIAS}", code="alias_not_found")

    async def embed(
        self,
        texts: list[str],
        *,
        alias: str,
        width: int | None,
        tenant: str,
        step: str,
        sensitivity: str = "internal",
    ) -> Embedded:
        """Vectors for `texts` from the embedding alias, `width` wide when given. One request for the batch; the
        caller keeps a batch within models-service's limit."""
        if not texts:
            return Embedded([], 0)
        body: dict[str, Any] = {"model": alias, "input": texts}
        if width is not None:
            body["dimensions"] = width
        try:
            r = await self.http.post(EMBED_ROUTE, headers=_headers(self.key, tenant, step, sensitivity), json=body)
        except httpx.HTTPError as e:
            raise _unreached(e) from e
        if r.status_code >= 400:
            raise refusal(r)
        return _embedded(r, len(texts))


@dataclass
class IngestModel:
    """ops_ingest's `ModelClient` on models-service: the split's AI steps are synchronous, so this runs on a blocking
    client and the caller runs the split in a worker thread. It counts the calls and tokens it spends, so a sync run
    records its real spend."""

    http: httpx.Client
    key: str
    tenant: str
    step: str
    sensitivity: str = "internal"
    # The run its calls belong to and that run's ceiling in money (X-Run-Id, X-Run-Spend-Cap): models-service refuses
    # a call once what it recorded for the run reaches it.
    run_id: str | None = None
    run_cap: str | None = None
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def complete(self, prompt: str, *, alias: str, max_tokens: int) -> str:
        try:
            r = self.http.post(
                CHAT_ROUTE,
                headers={
                    **_headers(self.key, self.tenant, self.step, self.sensitivity),
                    **({"X-Run-Id": self.run_id} if self.run_id else {}),
                    **({"X-Run-Spend-Cap": self.run_cap} if self.run_id and self.run_cap else {}),
                },
                json=_chat_body(alias, [{"role": "user", "content": prompt}], max_completion_tokens=max_tokens),
            )
        except httpx.HTTPError as e:
            raise _unreached(e) from e
        if r.status_code >= 400:
            raise refusal(r)
        try:
            data = cast(_ChatReply, r.json())
            usage = data.get("usage") or _Counted()
            tokens = (int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0))
            choice = data["choices"][0]
            message = choice["message"]
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
            raise ModelCallError(f"models-service's answer could not be read: {e!r}", code=UNREADABLE) from e
        # Counted before an ending is refused: models-service billed the reply either way.
        self.calls += 1
        self.input_tokens += tokens[0]
        self.output_tokens += tokens[1]
        text = message.get("content")
        answered = isinstance(text, str) and bool(text.strip())
        if (ended := _ending(message, choice.get("finish_reason"), answered=answered)) is not None:
            ended.alias = alias
            raise ended
        return cast(str, text)
