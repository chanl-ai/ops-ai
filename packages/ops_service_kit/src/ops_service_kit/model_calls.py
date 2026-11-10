"""The one client for a model call made by a service that is not an agent. The service holds its own model key (its
budget line in models-service, never a provider credential) and every call goes through models-service on an alias:

- `ModelCalls.structured`: a system and a user message, read back as the `final_result` function's arguments, the
  form the agent kernel asks structured output in;
- `ModelCalls.embed`: vectors for a batch of texts from an alias of kind embedding, with the tokens spent;
- `IngestModel.complete`: one prompt answered as text, for ingestion's AI steps, which run in a worker thread
  (`ops_ingest.ModelClient`).

A refusal keeps models-service's own code (`key_budget_exhausted`, `rate_limited`, `sensitivity_not_cleared`,
`alias_not_found`, ...) on `ModelCallError`, so a caller decides from the code rather than from the message.
documents-service's extraction carries its own copy of the call and moves onto this one in a follow-on."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

import httpx

# The alias a service's structured calls use while models-service has no alias of the service's own name.
FALLBACK_ALIAS = "default"
# Codes for a call that never reached models-service, or whose answer could not be read.
UNREACHABLE = "models_unreachable"
UNREADABLE = "models_answer_unreadable"


class ModelCallError(Exception):
    """models-service could not be reached, or refused the call with `code` and HTTP `status` (0 when unreached)."""

    def __init__(self, message: str, *, code: str = UNREACHABLE, status: int = 0) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class Embedded:
    """One vector per text, in the order sent, and the input tokens models-service charged for them."""

    vectors: list[list[float]]
    input_tokens: int


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
        error = cast(dict[str, Any], cast(dict[str, Any], r.json()).get("error") or {})
    except ValueError:
        error = {}
    code = str(error.get("code") or f"http_{r.status_code}")
    message = str(error.get("message") or r.text[:300])
    return ModelCallError(f"models-service answered {r.status_code} {code}: {message}", code=code, status=r.status_code)


def _chat_body(alias: str, messages: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"model": alias, "messages": messages, **extra}


def _structured_answer(r: httpx.Response) -> Any:
    message = cast(dict[str, Any], cast(dict[str, Any], r.json())["choices"][0]["message"])
    calls = cast(list[dict[str, Any]], message.get("tool_calls") or [])
    raw = calls[0]["function"]["arguments"] if calls else message.get("content")
    try:
        return json.loads(raw) if isinstance(raw, str) else {}
    except json.JSONDecodeError:
        return {}


def _embedded(r: httpx.Response, sent: int) -> Embedded:
    try:
        data = cast(dict[str, Any], r.json())
        rows = sorted(cast(list[dict[str, Any]], data["data"]), key=lambda d: int(d["index"]))
        vectors = [[float(x) for x in cast(list[Any], d["embedding"])] for d in rows]
        tokens = int(cast(dict[str, Any], data.get("usage") or {}).get("prompt_tokens", 0))
    except (ValueError, KeyError, TypeError) as e:
        raise ModelCallError(f"models-service's embeddings answer could not be read: {e}", code=UNREADABLE) from e
    if len(vectors) != sent:
        raise ModelCallError(f"models-service returned {len(vectors)} vectors for {sent} texts", code=UNREADABLE)
    return Embedded(vectors, tokens)


@dataclass
class ModelCalls:
    http: httpx.AsyncClient
    key: str
    alias: str = FALLBACK_ALIAS

    async def structured(
        self, system: str, user: str, schema: dict[str, Any], *, tenant: str, step: str, sensitivity: str = "internal"
    ) -> Any:
        """The answer's arguments; {} when the model answered with something unreadable, which fails the caller's own
        schema check rather than raising."""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        tools = [{"type": "function", "function": {"name": "final_result", "parameters": schema}}]
        for name in dict.fromkeys((self.alias, FALLBACK_ALIAS)):
            try:
                r = await self.http.post(
                    "/v1/models/chat/completions",
                    headers=_headers(self.key, tenant, step, sensitivity),
                    json=_chat_body(name, messages, tools=tools, tool_choice="required"),
                )
            except httpx.HTTPError as e:
                raise ModelCallError(f"models-service could not be reached: {e}") from e
            if r.status_code == 404 and "alias_not_found" in r.text and name != FALLBACK_ALIAS:
                continue
            if r.status_code >= 400:
                raise refusal(r)
            return _structured_answer(r)
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
            r = await self.http.post(
                "/v1/models/embeddings", headers=_headers(self.key, tenant, step, sensitivity), json=body
            )
        except httpx.HTTPError as e:
            raise ModelCallError(f"models-service could not be reached: {e}") from e
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
                "/v1/models/chat/completions",
                headers={
                    **_headers(self.key, self.tenant, self.step, self.sensitivity),
                    **({"X-Run-Id": self.run_id} if self.run_id else {}),
                    **({"X-Run-Spend-Cap": self.run_cap} if self.run_id and self.run_cap else {}),
                },
                json=_chat_body(alias, [{"role": "user", "content": prompt}], max_tokens=max_tokens),
            )
        except httpx.HTTPError as e:
            raise ModelCallError(f"models-service could not be reached: {e}") from e
        if r.status_code >= 400:
            raise refusal(r)
        self.calls += 1
        data = cast(dict[str, Any], r.json())
        usage = cast(dict[str, Any], data.get("usage") or {})
        self.input_tokens += int(usage.get("prompt_tokens", 0))
        self.output_tokens += int(usage.get("completion_tokens", 0))
        message = cast(dict[str, Any], cast(list[dict[str, Any]], data.get("choices") or [{}])[0].get("message") or {})
        return str(message.get("content") or "")
