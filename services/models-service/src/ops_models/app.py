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
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, cast

import httpx
from fastapi import Depends, FastAPI, Header, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from ops_access import Access
from ops_identity import Auth, CurrentPrincipal, CurrentTenantCaller, Principal, current_service, install_auth
from ops_metering import Price, Usage, cost
from ops_policy import CredentialStore
from ops_service_kit.credentials import credential_store
from ops_service_kit.errors import Conflict, NotFound
from ops_service_kit.http import Envelope, error_body, error_responses, install_error_handlers, ok, operation_id
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.settings import Settings
from ops_store import isolation
from ops_store.database import Database

from .connection_settings import azure_openai_problem
from .provider_keys import ProviderKeys
from .providers import AzureOpenAIProvider, ProviderError, StreamUsage, provider_for, region_mismatch
from .schemas import (
    Admission,
    AliasOut,
    AliasRef,
    CallPage,
    ChatCompletion,
    ChatCompletionRequest,
    Embeddings,
    EmbeddingsRequest,
    Health,
    KeyOut,
    KeyRotated,
    KeySecret,
    ProviderCreated,
    ProviderKeyOut,
    ProviderOut,
)
from .store import SENSITIVITY, Aliases, CallLog, ModelKeys, ProviderKeyStore, Providers, cleared


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


# The wire name of each field connection_problem names.
_FIELD = {"endpoint": "baseUrl", "api_version": "apiVersion"}


def connection_problem(kind: str, base_url: str | None, api_version: str | None, region: str | None) -> str | None:
    """Why a connection of `kind` with these values cannot be called, naming the field; None when it can. Azure's rule
    is the install settings' own (`connection_settings.azure_openai_problem`); only Azure connections carry an
    api-version or a region."""
    if kind == "azure-openai":
        problem = azure_openai_problem(base_url, api_version)
        return f"{_FIELD[problem[0]]} {problem[1]}" if problem else None
    if api_version is not None or region is not None:
        return "apiVersion and region apply to azure-openai connections only"
    if kind == "openai-compatible" and not base_url:
        return "baseUrl is missing: the endpoint's base URL, ending in /v1"
    return None


class ProviderIn(_Wire):
    name: str = Field(min_length=1, max_length=120)
    type: str = Field(pattern="^(openai-compatible|azure-openai|anthropic|scripted)$")
    base_url: str | None = Field(default=None, max_length=400)
    key_ref: str | None = Field(default=None, max_length=120)
    api_version: str | None = Field(default=None, max_length=32)
    region: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _callable(self) -> ProviderIn:
        if (why := connection_problem(self.type, self.base_url, self.api_version, self.region)) is not None:
            raise ValueError(why)
        return self


class ProviderRebind(_Wire):
    base_url: str = Field(min_length=1, max_length=400)
    key_ref: str | None = Field(default=None, max_length=120)
    api_version: str | None = Field(default=None, max_length=32)
    region: str | None = Field(default=None, max_length=64)


class ProviderKeyIn(_Wire):
    value: str = Field(min_length=1, max_length=4000)


# The name a provider connection's `key_ref` gives: `OPENAI`, or `openai` as the dev stack names it.
KEY_NAME = Path(pattern="^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")


class AliasVersionIn(_Wire):
    provider_id: str
    model_id: str
    cleared_sensitivity: str = Field(pattern="^(public|internal|confidential|restricted)$")
    input_per_million: Decimal = Decimal(0)
    output_per_million: Decimal = Decimal(0)
    # A reasoning model at its default effort thinks for seconds before its first word; chat aliases name a low one.
    reasoning_effort: str | None = Field(default=None, pattern="^(minimal|low|medium|high)$")
    # Cleared for page images: an image carries the whole page, so a version receives none unless set.
    images: bool = False


class AliasIn(AliasVersionIn):
    name: str = Field(pattern="^[a-z0-9][a-z0-9.-]{1,118}$")
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
# The most texts one embeddings request carries, as OpenAI's own limit: a sync embeds its pieces in batches of this.
MAX_EMBED_INPUTS = 2048


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


def _provider_view(r: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "name": r["name"],
        "type": r["type"],
        "baseUrl": r["base_url"],
        "keyRef": r["key_ref"],
        "apiVersion": r["api_version"],
        "region": r["region"],
        "observedRegion": r["observed_region"],
        "regionMismatch": region_mismatch(r["observed_region"], r["region"]),
    }


def _provider_key_view(r: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": r["name"],
        "version": r["version"],
        "createdBy": r["created_by"],
        "createdAt": r["created_at"].isoformat(),
        "rotatedAt": _iso(r["rotated_at"]),
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
    credentials: CredentialStore | None = None,
) -> FastAPI:
    """Tests inject `upstream`, the client provider calls go out on; otherwise one is opened and closed with the app.
    `auth` resolves callers (ops_identity's shared dependency); by default it is built from Settings for "models".
    Provider keys are the accounts' own (`provider_keys`), kept in `credentials` (the store the settings choose by
    default); `provider_secrets` are the dev stack's keys from settings, behind them."""
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
    settings = Settings()
    if settings.cors_origins:
        # The console calls the provider key and connection routes from the browser (Settings > Model providers).
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Content-Type", "Accept", "Authorization", "X-Team-Id"],
            max_age=600,
        )
    install_auth(app, auth or Auth.from_settings(settings, audience="models"))
    key_vault = ProviderKeyStore(db, credentials or credential_store(settings))
    keys = ProviderKeys(key_vault, provider_secrets)
    access = Access()
    providers, aliases, key_store, call_log = Providers(db), Aliases(db), ModelKeys(db), CallLog(db)

    # TODO(auth): every /v1/models/* route below takes a calling service's Ed25519 token (CurrentService), the same
    # as agents-service's alias lookup and key admission. Providers, keys and alias versions are also what a person
    # administers: when the console gets a models admin page, those routes move to CurrentPrincipal with an admin
    # role check, and only aliases, admit and calls stay service-only.
    guard = Depends(current_service)

    async def connections_caller(p: CurrentTenantCaller) -> Principal:
        """Provider connections are set up by an install's own scripts (a service token) or by an account admin on
        Settings > Model providers (settings.manage, as for provider keys): one API for both."""
        if p.kind != "service":
            access.can(p, "settings", "manage", what="model provider connections", code="admin_only")
        return p

    connections_guard = Depends(connections_caller)

    @app.get("/health", tags=["health"], response_model=Health)
    async def health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    connection_errors = error_responses({400: "A value the connection's type refuses", 403: "Not an account admin"})

    @app.get(
        "/v1/models/providers",
        dependencies=[connections_guard],
        tags=["providers"],
        response_model=Envelope[list[ProviderOut]],
        responses=connection_errors,
    )
    async def list_providers() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Every provider connection: where its calls go and the name of the key it signs in with, never a key."""
        return ok([_provider_view(r) for r in await providers.all()])

    @app.post(
        "/v1/models/providers",
        dependencies=[connections_guard],
        tags=["providers"],
        status_code=201,
        response_model=Envelope[ProviderCreated],
        responses=connection_errors,
    )
    async def create_provider(body: ProviderIn) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Adds a connection; 400 naming the field its type refuses (an Azure OpenAI connection needs its endpoint and
        api-version; its region is optional)."""
        pid = new_id("prov")
        row = {
            "id": pid,
            "name": body.name,
            "type": body.type,
            "base_url": body.base_url,
            "key_ref": body.key_ref,
            "api_version": body.api_version,
            "region": body.region,
        }
        if not await providers.create({**row, "created_at": now_iso()}):
            return refused(409, "provider_exists", f"A provider connection named {body.name} exists.")
        return ok({"id": pid, "name": body.name, "type": body.type}, status=201)

    @app.put(
        "/v1/models/providers/{provider_id}",
        dependencies=[connections_guard],
        tags=["providers"],
        response_model=Envelope[ProviderOut],
        responses=connection_errors,
    )
    async def rebind_provider(provider_id: str, body: ProviderRebind) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Points a connection at another endpoint, credential name, api-version and region. Every alias version bound
        to it follows on its next call, which is how one alias moves between a fake and the real provider without a
        new version."""
        row = await providers.get(provider_id)
        if row is None:
            return refused(404, "provider_not_found", f"No provider connection {provider_id}.")
        # A connection's type never changes after it is made, so the check holds without a lock.
        if row["type"] == "scripted":
            return refused(409, "provider_not_rebindable", "A scripted connection has no endpoint to change.")
        # An api-version or region left out keeps the stored one: the install scripts move only the base URL and key.
        given = body.model_fields_set
        version = body.api_version if "api_version" in given else row["api_version"]
        region = body.region if "region" in given else row["region"]
        if (why := connection_problem(row["type"], body.base_url, version, region)) is not None:
            return refused(400, "validation_failed", why)
        fields = {"base_url": body.base_url, "key_ref": body.key_ref, "api_version": version, "region": region}
        await providers.rebind(provider_id, fields)
        return ok(_provider_view({**row, **fields, "observed_region": None}))

    def account_admin(p: CurrentPrincipal) -> str:
        """settings.manage, held in the Security team: an account admin. Returns the actor."""
        access.can(p, "settings", "manage", what="model provider keys", code="admin_only")
        return p.email or p.sub

    key_errors = error_responses({403: "Not an account admin", 409: "A provider connection still uses the key"})

    @app.get(
        "/v1/provider-keys", tags=["provider-keys"], response_model=Envelope[list[ProviderKeyOut]], responses=key_errors
    )
    async def list_provider_keys(p: CurrentPrincipal) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The account's model provider keys by name; a value is never returned."""
        account_admin(p)
        return ok([_provider_key_view(r) for r in await key_vault.listed(p.tenant_id)])

    @app.put(
        "/v1/provider-keys/{name}",
        tags=["provider-keys"],
        response_model=Envelope[ProviderKeyOut],
        responses=key_errors,
    )
    async def save_provider_key(  # pyright: ignore[reportUnusedFunction]
        name: Annotated[str, KEY_NAME], body: ProviderKeyIn, p: CurrentPrincipal
    ) -> JSONResponse:
        """Saves a key under the name a provider connection's keyRef gives, or replaces its value. The next call
        through a connection naming it uses the new value."""
        by = account_admin(p)
        saved, _ = await key_vault.save(p.tenant_id, name, body.value, by=by)
        keys.forget(p.tenant_id, name)
        return ok(_provider_key_view(saved))

    @app.delete(
        "/v1/provider-keys/{name}",
        tags=["provider-keys"],
        status_code=204,
        response_class=Response,
        responses=key_errors,
    )
    async def delete_provider_key(name: Annotated[str, KEY_NAME], p: CurrentPrincipal) -> Response:  # pyright: ignore[reportUnusedFunction]
        """Deletes a key no provider connection names; 409 naming the connection that still does."""
        account_admin(p)
        using = [r["name"] for r in await providers.all() if r["key_ref"] == name]
        if using:
            raise Conflict(f"Provider connection {', '.join(using)} signs in with {name}.", code="key_in_use")
        if not await key_vault.delete(p.tenant_id, name):
            raise NotFound(f"Model provider key {name}")
        keys.forget(p.tenant_id, name)
        return Response(status_code=204)

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

    class Gate:
        """One authenticated call on its way to a provider: the key, the alias version it is served by, its price, and
        the one call-log row it writes, whether it is refused here, fails at the provider or settles."""

        def __init__(self, key: Mapping[str, Any], row: dict[str, Any], tenant: str | None) -> None:
            self.key, self.row, self.tenant = key, row, tenant
            self.started = time.perf_counter()
            self.version: dict[str, Any] = {}
            self.alias_row: Mapping[str, Any] = {}
            self.price = Price(Decimal(0))
            self.provider: Any = None

        async def log(self, outcome: str, reason: str | None = None, **values: Any) -> None:
            await call_log.record(
                {
                    "id": new_id("mc"),
                    "input_tokens": values.pop("input_tokens", 0),
                    "output_tokens": values.pop("output_tokens", 0),
                    "cost": values.pop("cost", Decimal(0)),
                    "latency_ms": int((time.perf_counter() - self.started) * 1000),
                    "outcome": outcome,
                    "reason": reason,
                    **self.row,
                    **values,
                }
            )

        async def refuse(self, status: int, code: str, message: str, *, versioned: bool = True) -> JSONResponse:
            await self.log("error" if status >= 500 else "denied", code, **(self.version if versioned else {}))
            return refused(status, code, message)

        async def settle(self, input_tokens: int, output_tokens: int) -> None:
            spend = cost(Usage(input_tokens=input_tokens, output_tokens=output_tokens), self.price)
            tenant = self.tenant if self.key["tenant_budget"] is not None else None
            if tenant is not None:
                with isolation.scope(tenant, None):
                    await key_store.spend(self.key["id"], spend, tenant_id=tenant)
            else:
                await key_store.spend(self.key["id"], spend)
            # An Azure answer from another region than its connection names is recorded on the row, not refused.
            provider = self.provider
            mismatch = provider.region_mismatch if isinstance(provider, AzureOpenAIProvider) else None
            values = {"input_tokens": input_tokens, "output_tokens": output_tokens, "cost": spend}
            await self.log("ok", mismatch[:64] if mismatch else None, **values, **self.version)

        async def observed(self) -> None:
            """Records the region an Azure resource answered from on its connection, when it changed."""
            provider = self.provider
            seen = provider.observed_region if isinstance(provider, AzureOpenAIProvider) else None
            if seen and seen != self.alias_row.get("observed_region"):
                await providers.observe(str(self.alias_row["provider_id"]), seen)

        async def failed(self, e: Exception) -> JSONResponse:
            await self.observed()
            await self.log("error", "provider_error", **self.version)
            return refused(502, "provider_error", str(e) or "The provider answered with an empty stream.")

    async def open_gate(
        authorization: str | None,
        alias_name: str,
        kind: str,
        *,
        sensitivity: str,
        tenant: str | None,
        images: int = 0,
        run_cap: str | None = None,
        **row: str | None,
    ) -> Gate | JSONResponse:
        """Every check a model call passes before it reaches a provider, in one order for chat and embeddings: the
        key, its budget and the tenant's share, the rate limit, the alias and its kind, the data's sensitivity, images,
        and the account's provider key."""
        presented = (authorization or "").removeprefix("Bearer ").strip()
        now = datetime.now(UTC)
        key = await key_store.by_secret(secret_hash(presented) if presented else "", now)
        if key is None:
            return refused(401, "invalid_key", "The model key is unknown, or a rotated secret past its overlap.")
        row_values = {"key_id": key["id"], "alias": alias_name, "sensitivity": sensitivity, "tenant_id": tenant}
        gate = Gate(key, {**row_values, **row, "images": images}, tenant)
        if (why := _key_refusal(key, now)) is not None:
            return await gate.refuse(*why)
        if key["tenant_budget"] is not None:
            # A key one service spends for many tenants: the tenant names its own budget row.
            if not tenant:
                return await gate.refuse(
                    400, "tenant_required", f"Model key {key['id']} spends per tenant; send X-Tenant-Id."
                )
            # The share is the named tenant's: read as that tenant, which the database holds the row to.
            with isolation.scope(tenant, None):
                share = await key_store.tenant_share(key["id"], tenant, key["tenant_budget"])
            if share["spent"] >= share["budget"]:
                return await gate.refuse(
                    429,
                    "tenant_budget_exhausted",
                    f"Tenant {tenant} has spent its budget of {share['budget']} on model key {key['id']}.",
                )
        if key.get("daily_cap") is not None:
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
            if await call_log.spent(key["id"], since=today) >= key["daily_cap"]:
                return await gate.refuse(
                    429, "daily_spend_cap", f"Model key {key['id']} has spent its {key['daily_cap']} for today."
                )
        if run_cap is not None and row.get("run_id"):
            try:
                cap = Decimal(run_cap)
            except InvalidOperation:
                return await gate.refuse(400, "invalid_spend_cap", "X-Run-Spend-Cap is an amount, such as 5.00.")
            if await call_log.spent(key["id"], run_id=row["run_id"]) >= cap:
                return await gate.refuse(
                    429, "run_spend_cap", f"Run {row['run_id']} has spent its {cap} on model key {key['id']}."
                )
        # The log's times are the database's, so the one-minute window is measured on the database's clock too.
        recent = await call_log.recent(key["id"])
        alias_row = await aliases.current(alias_name)
        if recent >= key["rate_limit_per_minute"]:
            return await gate.refuse(
                429, "rate_limited", f"Model key {key['id']} is over {key['rate_limit_per_minute']} calls a minute."
            )
        if alias_row is None:
            return await gate.refuse(404, "alias_not_found", f"No current version of alias {alias_name}.")
        gate.alias_row = alias_row
        gate.version = {"alias_version": alias_row["version"], "provider_model": alias_row["model_id"]}
        if alias_row["kind"] != kind:
            return await gate.refuse(
                400, "alias_kind_mismatch", f"Alias {alias_name} is a {alias_row['kind']} alias, not {kind}."
            )
        if sensitivity not in SENSITIVITY or not cleared(alias_row["cleared_sensitivity"], sensitivity):
            return await gate.refuse(
                403,
                "sensitivity_not_cleared",
                f"Alias {alias_name} is cleared for {alias_row['cleared_sensitivity']} data, not {sensitivity}.",
            )
        if images and not alias_row["images"]:
            return await gate.refuse(
                403, "images_not_cleared", f"Alias {alias_name} is not cleared for images or files."
            )
        gate.price = Price(alias_row["input_per_million"], alias_row["output_per_million"])
        ref = alias_row.get("key_ref")
        if ref and not tenant:
            # A provider key is an account's own: a call that names no account signs in with none.
            return await gate.refuse(
                400,
                "tenant_required",
                f"Alias {alias_name} signs in with an account's model provider key {ref}; send X-Tenant-Id.",
            )
        provider_key = await keys.get(str(ref), str(tenant)) if ref else None
        if ref and provider_key is None:
            # Calling the provider without its key would only come back as its own 401, after a network round trip.
            return await gate.refuse(
                503,
                "provider_key_missing",
                f"Alias {alias_name} signs in with model provider key {ref}, which the account has not saved. An "
                "account admin adds it on Settings > Model providers.",
            )
        try:
            gate.provider = provider_for(alias_row, {str(ref): provider_key} if ref and provider_key else {}, http)
        except ProviderError as e:
            return await gate.refuse(502, "provider_error", str(e))
        return gate

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
        x_run_spend_cap: Annotated[str | None, Header()] = None,
    ) -> Response:
        body = request.model_dump(exclude_unset=True)
        alias_name = request.model
        gate = await open_gate(
            authorization,
            alias_name,
            "chat",
            sensitivity=x_data_sensitivity,
            tenant=x_tenant_id,
            images=images_in(request.messages),
            run_cap=x_run_spend_cap,
            run_id=x_run_id,
            step_id=x_step_id,
            thread_id=x_thread_id,
            request_hash=x_request_hash,
        )
        if isinstance(gate, JSONResponse):
            return gate
        alias_row, provider, version = gate.alias_row, gate.provider, gate.version
        log, settle, observed, failed = gate.log, gate.settle, gate.observed, gate.failed
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
                return await failed(e)
            await observed()

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
            return await failed(e)
        await observed()
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
    provider_errors = {
        502: "The provider refused or failed",
        503: "The provider key the connection names is not saved",
    }
    app.post(
        "/v1/models/chat/completions",
        tags=["completions"],
        response_model=ChatCompletion,
        responses={200: {"content": {"text/event-stream": {}}}, **error_responses(provider_errors)},
    )(completions)

    async def embeddings(
        request: EmbeddingsRequest,
        *,
        authorization: Annotated[str | None, Header()] = None,
        x_data_sensitivity: Annotated[str, Header()] = "internal",
        x_run_id: Annotated[str | None, Header()] = None,
        x_step_id: Annotated[str | None, Header()] = None,
        x_tenant_id: Annotated[str | None, Header()] = None,
        x_run_spend_cap: Annotated[str | None, Header()] = None,
    ) -> Response:
        """Vectors for one text or a batch, from an alias of kind embedding, through the same key, budget and clearance
        checks as a completion, and one call-log row per request."""
        inputs = [request.input] if isinstance(request.input, str) else list(request.input)
        gate = await open_gate(
            authorization,
            request.model,
            "embedding",
            sensitivity=x_data_sensitivity,
            tenant=x_tenant_id,
            run_cap=x_run_spend_cap,
            run_id=x_run_id,
            step_id=x_step_id,
        )
        if isinstance(gate, JSONResponse):
            return gate
        if not inputs or len(inputs) > MAX_EMBED_INPUTS:
            return await gate.refuse(
                400, "invalid_input", f"Send 1 to {MAX_EMBED_INPUTS} texts to embed, not {len(inputs)}."
            )
        try:
            done = await gate.provider.embed(str(gate.alias_row["model_id"]), inputs, request.dimensions)
        except ProviderError as e:
            return await gate.failed(e)
        await gate.observed()
        await gate.settle(done.input_tokens, 0)
        return JSONResponse(
            {
                "object": "list",
                "model": request.model,
                "data": [{"object": "embedding", "index": i, "embedding": v} for i, v in enumerate(done.vectors)],
                "usage": {"prompt_tokens": done.input_tokens, "total_tokens": done.input_tokens},
            }
        )

    app.post(
        "/v1/models/embeddings",
        tags=["completions"],
        response_model=Embeddings,
        responses=error_responses(provider_errors),
    )(embeddings)

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
