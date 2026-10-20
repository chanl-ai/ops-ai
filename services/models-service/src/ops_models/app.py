"""models-service routes.

Admin and admission routes are internal (the service token). `/v1/models/chat/completions` is OpenAI-compatible
and streams when asked. It is authenticated by the model key's own secret, so a worker holds a key and never a
provider credential. Every authenticated completion writes exactly one `model_call_log` row, a denial included,
with no prompt or completion text in it.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
from collections.abc import AsyncGenerator, AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any, cast

import httpx
from fastapi import Depends, FastAPI, Header, Query
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ops_identity import Auth, current_service, install_auth
from ops_metering import Price, Usage, cost
from ops_service_kit.http import Envelope, error_body, error_responses, install_error_handlers, ok
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.settings import Settings
from ops_store.database import Database

from .provider_keys import ProviderKeys
from .providers import ProviderError, StreamUsage, provider_for
from .schemas import (
    Admission,
    AliasOut,
    AliasRef,
    CallPage,
    ChatCompletion,
    ChatCompletionRequest,
    Health,
    KeyOut,
    KeyRotated,
    KeySecret,
    ProviderCreated,
    ProviderOut,
)
from .store import SENSITIVITY, Aliases, CallLog, ModelKeys, Providers, cleared


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class ProviderIn(_Wire):
    name: str
    type: str = Field(pattern="^(openai-compatible|anthropic|scripted)$")
    base_url: str | None = None
    key_ref: str | None = None


class ProviderRebind(_Wire):
    base_url: str = Field(min_length=1, max_length=400)
    key_ref: str | None = None


class AliasVersionIn(_Wire):
    provider_id: str
    model_id: str
    cleared_sensitivity: str = Field(pattern="^(public|internal|confidential|restricted)$")
    input_per_million: Decimal = Decimal(0)
    output_per_million: Decimal = Decimal(0)
    # A reasoning model at its default effort thinks for seconds before its first word; chat aliases name a low one.
    reasoning_effort: str | None = Field(default=None, pattern="^(minimal|low|medium|high)$")
    # Cleared for page images (c-295): an image carries the whole page, so a version receives none unless set.
    images: bool = False


class AliasIn(AliasVersionIn):
    name: str = Field(pattern="^[a-z0-9][a-z0-9-]{1,118}$")
    kind: str = Field(default="chat", pattern="^(chat|embedding)$")


class KeyIn(_Wire):
    id: str = Field(min_length=3, max_length=200)
    kind: str = Field(pattern="^(workflow|agent|user|purpose)$")
    budget: Decimal = Field(ge=0)
    rate_limit_per_minute: int = Field(default=600, ge=1)
    expires_at: datetime | None = None


class RotateIn(_Wire):
    overlap_seconds: int | None = Field(default=None, ge=0)


class AdmitIn(_Wire):
    key_id: str
    alias: str | None = None
    estimated_tokens: int | None = Field(default=None, ge=0)


ERRORS = error_responses()


def operation_id(route: APIRoute) -> str:
    """`<tag>_<handler>`, e.g. `keys_issue_key`: stable across path changes, and the name a generated SDK uses."""
    return f"{route.tags[0]}_{route.name}".lower() if route.tags else route.name


def secret_hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def new_secret() -> str:
    return "mk_" + secrets.token_urlsafe(24)


def refused(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(error_body(status, code, message), status_code=status)


def _iso(v: datetime | None) -> str | None:
    return v.isoformat() if v is not None else None


def _key_view(r: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "kind": r["kind"],
        "budget": str(r["budget"]),
        "spent": str(r["spent"]),
        "rateLimitPerMinute": r["rate_limit_per_minute"],
        "expiresAt": _iso(r["expires_at"]),
        "status": r["status"],
        "rotatedAt": _iso(r["rotated_at"]),
        "previousValidUntil": _iso(r["previous_valid_until"]),
    }


def _alias_view(r: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": r["name"],
        "version": r["version"],
        "kind": r["kind"],
        "providerId": r["provider_id"],
        "modelId": r["model_id"],
        "clearedSensitivity": r["cleared_sensitivity"],
        "inputPerMillion": str(r["input_per_million"]),
        "outputPerMillion": str(r["output_per_million"]),
        "status": r["status"],
        "reasoningEffort": r.get("reasoning_effort"),
        "images": bool(r.get("images")),
    }


def _key_refusal(key: Mapping[str, Any], now: datetime) -> tuple[int, str, str] | None:
    """Why a key may not spend right now: revoked, expired or at its budget. None when it may."""
    if key["status"] != "active":
        return 403, "key_revoked", f"Model key {key['id']} is revoked."
    if key["expires_at"] is not None and key["expires_at"] <= now:
        return 403, "key_expired", f"Model key {key['id']} expired at {key['expires_at'].isoformat()}."
    if key["spent"] >= key["budget"]:
        return 429, "key_budget_exhausted", f"Model key {key['id']} has spent its budget of {key['budget']}."
    return None


def create_models_app(
    db: Database,
    *,
    auth: Auth | None = None,
    provider_secrets: Mapping[str, str] | None = None,
    overlap_seconds: int = 900,
    upstream: httpx.AsyncClient | None = None,
    provider_keys: ProviderKeys | None = None,
) -> FastAPI:
    """Tests inject `upstream`, the client provider calls go out on; otherwise one is opened and closed with the app.
    `auth` resolves callers (ops_identity's shared dependency); by default it is built from Settings for "models".
    `provider_keys` reads a connection's key from the Secrets store (c-177); without it only `provider_secrets` (the
    dev stack's settings) answer."""
    http = upstream or httpx.AsyncClient(timeout=60)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        yield
        if upstream is None:
            await http.aclose()

    app = FastAPI(
        title="Ops AI models service",
        version="0.1.0",
        lifespan=lifespan,
        generate_unique_id_function=operation_id,
    )
    install_error_handlers(app)
    install_auth(app, auth or Auth.from_settings(Settings(), audience="models"))
    keys = provider_keys or ProviderKeys(None, provider_secrets)
    providers, aliases, key_store, call_log = Providers(db), Aliases(db), ModelKeys(db), CallLog(db)

    # TODO(auth): every /v1/models/* route below takes a calling service's Ed25519 token (CurrentService), the same
    # as agents-service's alias lookup and key admission. Providers, keys and alias versions are also what a person
    # administers: when the console gets a models admin page, those routes move to CurrentPrincipal with an admin
    # role check, and only aliases, admit and calls stay service-only.
    guard = Depends(current_service)

    @app.get("/health", tags=["health"], response_model=Health)
    async def health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    @app.get(
        "/v1/models/providers",
        dependencies=[guard],
        tags=["providers"],
        response_model=Envelope[list[ProviderOut]],
        responses=ERRORS,
    )
    async def list_providers() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(
            [
                {"id": r["id"], "name": r["name"], "type": r["type"], "baseUrl": r["base_url"], "keyRef": r["key_ref"]}
                for r in await providers.all()
            ]
        )

    @app.post(
        "/v1/models/providers",
        dependencies=[guard],
        tags=["providers"],
        status_code=201,
        response_model=Envelope[ProviderCreated],
        responses=ERRORS,
    )
    async def create_provider(body: ProviderIn) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        pid = new_id("prov")
        row = {"id": pid, "name": body.name, "type": body.type, "base_url": body.base_url, "key_ref": body.key_ref}
        if not await providers.create({**row, "created_at": now_iso()}):
            return refused(409, "provider_exists", f"A provider connection named {body.name} exists.")
        return ok({"id": pid, "name": body.name, "type": body.type}, status=201)

    @app.put(
        "/v1/models/providers/{provider_id}",
        dependencies=[guard],
        tags=["providers"],
        response_model=Envelope[ProviderOut],
        responses=ERRORS,
    )
    async def rebind_provider(provider_id: str, body: ProviderRebind) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Points a connection at another endpoint and credential name. Every alias version bound to it follows on its
        next call, which is how one alias moves between a fake and the real provider without a new version."""
        row = await providers.get(provider_id)
        if row is None:
            return refused(404, "provider_not_found", f"No provider connection {provider_id}.")
        # A connection's type never changes after it is made, so the check holds without a lock.
        if row["type"] == "scripted":
            return refused(409, "provider_not_rebindable", "A scripted connection has no endpoint to change.")
        await providers.rebind(provider_id, body.base_url, body.key_ref)
        view = {"id": provider_id, "name": row["name"], "type": row["type"], "baseUrl": body.base_url}
        return ok({**view, "keyRef": body.key_ref})

    @app.get(
        "/v1/models/aliases",
        dependencies=[guard],
        tags=["aliases"],
        response_model=Envelope[list[AliasOut]],
        responses=ERRORS,
    )
    async def list_aliases() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok([_alias_view(cur) for cur in await aliases.all_current()])

    @app.post(
        "/v1/models/aliases",
        dependencies=[guard],
        tags=["aliases"],
        status_code=201,
        response_model=Envelope[AliasRef],
        responses=ERRORS,
    )
    async def create_alias(body: AliasIn) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        if not await aliases.create(body.name, body.kind, _version_fields(body)):
            return refused(409, "alias_exists", f"Alias {body.name} exists; add a version instead.")
        return ok({"name": body.name, "version": 1}, status=201)

    @app.get(
        "/v1/models/aliases/{name}/versions",
        dependencies=[guard],
        tags=["aliases"],
        response_model=Envelope[list[AliasOut]],
        responses=ERRORS,
    )
    async def list_versions(name: str) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        rows = [_alias_view(r) for r in await aliases.versions(name)]
        return ok(rows) if rows else refused(404, "alias_not_found", f"No alias {name}.")

    @app.post(
        "/v1/models/aliases/{name}/versions",
        dependencies=[guard],
        tags=["aliases"],
        status_code=201,
        response_model=Envelope[AliasRef],
        responses=ERRORS,
    )
    async def add_version(name: str, body: AliasVersionIn) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        # Versions are immutable: a change is a new version, which replaces the one serving.
        version = await aliases.add_version(name, _version_fields(body))
        if version is None:
            return refused(404, "alias_not_found", f"No alias {name}.")
        return ok({"name": name, "version": version}, status=201)

    @app.get(
        "/v1/models/keys", dependencies=[guard], tags=["keys"], response_model=Envelope[list[KeyOut]], responses=ERRORS
    )
    async def list_keys() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok([_key_view(r) for r in await key_store.all()])

    @app.post(
        "/v1/models/keys",
        dependencies=[guard],
        tags=["keys"],
        status_code=201,
        response_model=Envelope[KeySecret],
        responses=ERRORS,
    )
    async def issue_key(body: KeyIn) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        secret = new_secret()
        row = {"id": body.id, "kind": body.kind, "budget": body.budget, "spent": Decimal(0), "status": "active"}
        limits = {"rate_limit_per_minute": body.rate_limit_per_minute, "expires_at": body.expires_at}
        if not await key_store.issue({**row, **limits, "secret_hash": secret_hash(secret)}):
            return refused(409, "key_exists", f"A key for {body.id} exists; rotate it instead.")
        # The secret is returned once and stored only as a hash.
        return ok({"id": body.id, "secret": secret}, status=201)

    @app.post(
        "/v1/models/keys/{key_id}/rotate",
        dependencies=[guard],
        tags=["keys"],
        response_model=Envelope[KeyRotated],
        responses=ERRORS,
    )
    async def rotate_key(key_id: str, body: RotateIn) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        secret = new_secret()
        overlap = body.overlap_seconds if body.overlap_seconds is not None else overlap_seconds
        now = datetime.now(UTC)
        if not await key_store.rotate(key_id, secret_hash(secret), now + timedelta(seconds=overlap), now):
            return refused(404, "key_not_found", f"No key {key_id}.")
        return ok(
            {"id": key_id, "secret": secret, "previousValidUntil": (now + timedelta(seconds=overlap)).isoformat()}
        )

    @app.get(
        "/v1/models/calls", dependencies=[guard], tags=["calls"], response_model=Envelope[CallPage], responses=ERRORS
    )
    async def list_calls(  # pyright: ignore[reportUnusedFunction]
        key_id: Annotated[str | None, Query(alias="keyId")] = None,
        alias: str | None = None,
        outcome: str | None = None,
        thread_id: Annotated[str | None, Query(alias="threadId")] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> JSONResponse:
        rows, totals = await call_log.page(
            key_id=key_id, alias=alias, outcome=outcome, thread_id=thread_id, limit=limit
        )
        items = [
            {
                "id": r["id"],
                "keyId": r["key_id"],
                "alias": r["alias"],
                "aliasVersion": r["alias_version"],
                "providerModel": r["provider_model"],
                "inputTokens": r["input_tokens"],
                "outputTokens": r["output_tokens"],
                "cost": str(r["cost"]),
                "latencyMs": r["latency_ms"],
                "outcome": r["outcome"],
                "reason": r["reason"],
                "runId": r["run_id"],
                "stepId": r["step_id"],
                "threadId": r["thread_id"],
                "requestHash": r["request_hash"],
                "createdAt": _iso(r["created_at"]),
                "images": r["images"],
            }
            for r in rows
        ]
        by_key = [{"keyId": k, "calls": n, "cost": str(c)} for k, n, c in totals]
        return ok({"items": items, "byKey": by_key})

    @app.post(
        "/v1/models/admit",
        dependencies=[guard],
        tags=["admission"],
        response_model=Envelope[Admission],
        responses=ERRORS,
    )
    async def admit(body: AdmitIn) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """agents-service asks before it opens a thread. An unregistered identity is refused: every caller that
        spends on models needs a key with a budget."""
        key = await key_store.get(body.key_id)
        if key is None:
            return refused(403, "key_not_registered", f"No model key is registered for {body.key_id}.")
        if (why := _key_refusal(key, datetime.now(UTC))) is not None:
            return refused(*why)
        remaining: Decimal = key["budget"] - key["spent"]
        if body.alias and body.estimated_tokens:
            alias_row = await aliases.current(body.alias)
            if alias_row is not None:
                estimate = cost(Usage(input_tokens=body.estimated_tokens), Price(alias_row["input_per_million"]))
                if estimate > remaining:
                    return refused(429, "key_budget_exhausted", f"The estimate {estimate} exceeds {remaining} left.")
        return ok({"admitted": True, "remaining": str(remaining)})

    async def completions(
        request: ChatCompletionRequest,
        *,
        authorization: Annotated[str | None, Header()] = None,
        x_data_sensitivity: Annotated[str, Header()] = "internal",
        x_run_id: Annotated[str | None, Header()] = None,
        x_step_id: Annotated[str | None, Header()] = None,
        x_thread_id: Annotated[str | None, Header()] = None,
        x_request_hash: Annotated[str | None, Header()] = None,
        x_tenant_id: Annotated[str | None, Header()] = None,
    ) -> Response:
        presented = (authorization or "").removeprefix("Bearer ").strip()
        now = datetime.now(UTC)
        digest = secret_hash(presented) if presented else ""
        key = await key_store.by_secret(digest, now)
        if key is None:
            return refused(401, "invalid_key", "The model key is unknown, or a rotated secret past its overlap.")
        body = request.model_dump(exclude_unset=True)
        alias_name = request.model
        started = time.perf_counter()
        row: dict[str, Any] = {
            "key_id": key["id"],
            "alias": alias_name,
            "sensitivity": x_data_sensitivity,
            "run_id": x_run_id,
            "step_id": x_step_id,
            "thread_id": x_thread_id,
            "request_hash": x_request_hash,
            "tenant_id": x_tenant_id,
            "images": images_in(request.messages),
        }

        async def log(outcome: str, reason: str | None = None, **values: Any) -> None:
            await call_log.record(
                {
                    "id": new_id("mc"),
                    "input_tokens": values.pop("input_tokens", 0),
                    "output_tokens": values.pop("output_tokens", 0),
                    "cost": values.pop("cost", Decimal(0)),
                    "latency_ms": int((time.perf_counter() - started) * 1000),
                    "outcome": outcome,
                    "reason": reason,
                    **row,
                    **values,
                }
            )

        if (why := _key_refusal(key, now)) is not None:
            await log("denied", why[1])
            return refused(*why)
        if key["tenant_budget"] is not None:
            # A key one service spends for many tenants (c-251): the tenant names its own budget row.
            if not x_tenant_id:
                await log("denied", "tenant_required")
                return refused(400, "tenant_required", f"Model key {key['id']} spends per tenant; send X-Tenant-Id.")
            share = await key_store.tenant_share(key["id"], x_tenant_id, key["tenant_budget"])
            if share["spent"] >= share["budget"]:
                await log("denied", "tenant_budget_exhausted")
                return refused(
                    429,
                    "tenant_budget_exhausted",
                    f"Tenant {x_tenant_id} has spent its budget of {share['budget']} on model key {key['id']}.",
                )
        # The log's times are the database's, so the one-minute window is measured on the database's clock too.
        recent = await call_log.recent(key["id"])
        alias_row = await aliases.current(alias_name)
        if recent >= key["rate_limit_per_minute"]:
            await log("denied", "rate_limited")
            return refused(
                429, "rate_limited", f"Model key {key['id']} is over {key['rate_limit_per_minute']} calls a minute."
            )
        if alias_row is None:
            await log("denied", "alias_not_found")
            return refused(404, "alias_not_found", f"No current version of alias {alias_name}.")
        version = {"alias_version": alias_row["version"], "provider_model": alias_row["model_id"]}
        if x_data_sensitivity not in SENSITIVITY or not cleared(alias_row["cleared_sensitivity"], x_data_sensitivity):
            await log("denied", "sensitivity_not_cleared", **version)
            return refused(
                403,
                "sensitivity_not_cleared",
                f"Alias {alias_name} is cleared for {alias_row['cleared_sensitivity']} data, not {x_data_sensitivity}.",
            )
        if row["images"] and not alias_row["images"]:
            await log("denied", "images_not_cleared", **version)
            return refused(403, "images_not_cleared", f"Alias {alias_name} is not cleared for images or files.")
        price = Price(alias_row["input_per_million"], alias_row["output_per_million"])

        async def settle(input_tokens: int, output_tokens: int) -> None:
            spend = cost(Usage(input_tokens=input_tokens, output_tokens=output_tokens), price)
            tenant = x_tenant_id if key["tenant_budget"] is not None else None
            await key_store.spend(key["id"], spend, tenant_id=tenant)
            await log("ok", None, input_tokens=input_tokens, output_tokens=output_tokens, cost=spend, **version)

        ref = alias_row.get("key_ref")
        provider_key = await keys.get(str(ref)) if ref else None
        try:
            provider = provider_for(alias_row, {str(ref): provider_key} if ref and provider_key else {}, http)
        except ProviderError as e:
            await log("error", "provider_error", **version)
            return refused(502, "provider_error", str(e))
        if alias_row.get("reasoning_effort") and "reasoning_effort" not in body:
            body["reasoning_effort"] = alias_row["reasoning_effort"]
        call_id = new_id("chatcmpl")
        created = int(time.time())
        if request.stream:
            usage = StreamUsage()
            chunks = provider.stream(str(alias_row["model_id"]), body, usage)
            # The first chunk is read before answering, so a provider that refuses the request is a 502, not a 200
            # stream that ends early.
            try:
                first = await anext(chunks)
            except (ProviderError, StopAsyncIteration) as e:
                await log("error", "provider_error", **version)
                return refused(502, "provider_error", str(e) or "The provider answered with an empty stream.")

            async def events() -> AsyncIterator[str]:
                settling: asyncio.Task[None] | None = None
                try:
                    pending: dict[str, Any] | None = first
                    while pending is not None:
                        out = {**pending, "id": call_id, "created": created, "model": alias_name}
                        yield f"data: {json.dumps(out)}\n\n"
                        pending = await anext(chunks, None)
                    # Spend and the log row are written before the client sees the end: once it has [DONE] it
                    # disconnects, and Starlette cancels whatever this generator is still awaiting.
                    settling = asyncio.ensure_future(settle(usage.input_tokens, usage.output_tokens))
                    await asyncio.shield(settling)
                    yield "data: [DONE]\n\n"
                except ProviderError:
                    pass
                finally:
                    if settling is None:
                        # A provider failure or a client gone mid-stream: one error row, shielded from the cancel.
                        await asyncio.shield(log("error", "provider_error", **version))

            return StreamingResponse(events(), media_type="text/event-stream")
        try:
            done = await provider.complete(str(alias_row["model_id"]), body)
        except ProviderError as e:
            await log("error", "provider_error", **version)
            return refused(502, "provider_error", str(e))
        await settle(done.input_tokens, done.output_tokens)
        message: dict[str, Any] = {"role": "assistant", "content": done.text}
        if done.tool_calls:
            message["tool_calls"] = done.tool_calls
        return JSONResponse(
            {
                "id": call_id,
                "object": "chat.completion",
                "created": created,
                "model": alias_name,
                "choices": [{"index": 0, "message": message, "finish_reason": done.finish_reason}],
                "usage": {
                    "prompt_tokens": done.input_tokens,
                    "completion_tokens": done.output_tokens,
                    "total_tokens": done.input_tokens + done.output_tokens,
                },
            }
        )

    # OpenAI's path shape: clients built on the OpenAI SDK append `/chat/completions` to their base URL.
    app.post(
        "/v1/models/chat/completions",
        tags=["completions"],
        response_model=ChatCompletion,
        responses={200: {"content": {"text/event-stream": {}}}, **ERRORS},
    )(completions)

    return app


def _version_fields(body: AliasVersionIn) -> dict[str, Any]:
    return {
        "provider_id": body.provider_id,
        "model_id": body.model_id,
        "cleared_sensitivity": body.cleared_sensitivity,
        "input_per_million": body.input_per_million,
        "output_per_million": body.output_per_million,
        "reasoning_effort": body.reasoning_effort,
        "images": body.images,
    }


# The content part types that carry only text. Every other part (an image, a file, audio, or a kind no provider has
# named yet) counts as carrying the page, so a new part type is refused by an alias not cleared rather than let through.
TEXT_PARTS = frozenset({"text", "input_text", "output_text", "refusal"})


def images_in(messages: list[dict[str, Any]]) -> int:
    """How many parts of the request's messages carry something other than text; a string content carries none."""
    count = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            for part in cast(list[Any], content):
                kind = cast(dict[str, Any], part).get("type") if isinstance(part, dict) else None
                count += kind not in TEXT_PARTS
    return count
