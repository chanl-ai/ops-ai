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
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Coroutine, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal, TypedDict, cast
from urllib.parse import urlsplit

import httpx
from fastapi import Depends, FastAPI, Header, Path, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ops_access import Access
from ops_identity import (
    Auth,
    CurrentPrincipal,
    CurrentTenantCaller,
    Principal,
    ServiceClient,
    current_service,
    install_auth,
)
from ops_identity.fastapi import Tx
from ops_metering import Price, Usage, cost
from ops_policy import CredentialStore
from ops_service_kit.background import BackgroundHealthOut
from ops_service_kit.credentials import credential_store
from ops_service_kit.errors import (
    ApiError,
    Conflict,
    Forbidden,
    NotFound,
    TooManyRequests,
    Unauthorized,
    Unprocessable,
    ValidationFailed,
)
from ops_service_kit.http import (
    Envelope,
    In,
    Json,
    ListResult,
    Out,
    error_body,
    error_responses,
    install_error_handlers,
    ok,
    operation_id,
)
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.listing import ListParams, ListQuery
from ops_service_kit.logging import get_logger
from ops_service_kit.narrow import an_object, json_object
from ops_service_kit.public_address import PublicFetch
from ops_service_kit.settings import Settings
from ops_store import isolation
from ops_store.background import LOCAL as LOCAL_BEATS
from ops_store.background import report as background_report
from ops_store.database import Database

from .alias_users import AgentsAliasUsers, AliasUsers, NoAliasUsers
from .catalog import Catalog, CatalogModel
from .connection_settings import azure_openai_problem
from .key_check import EndpointRefused, KeyRefused, azure_host, listed_models
from .provider_keys import ProviderKeys
from .providers import ADAPTERS, AzureOpenAIProvider, ProviderError, StreamUsage, provider_for, region_mismatch
from .registry import BUILTIN, ProviderEntry, load_registry
from .schemas import (
    Admission,
    AliasOut,
    AliasRef,
    CallOut,
    CallPage,
    CatalogModelOut,
    ChatChoice,
    ChatCompletion,
    ChatCompletionRequest,
    ChatMessage,
    ChatUsage,
    EmbeddingRow,
    Embeddings,
    EmbeddingsRequest,
    EmbeddingsUsage,
    Health,
    KeyOut,
    KeyRotated,
    KeySecret,
    KeySpend,
    KnobsOut,
    ProviderCreated,
    ProviderKeyOut,
    ProviderOut,
    ProviderTypeOut,
    ToolCall,
    ToolFunction,
)
from .store import SENSITIVITY, Aliases, CallLog, ModelKeys, ProviderKeyStore, Providers, cleared
from .store.aliases import AliasFields, AliasRow, ServingAlias
from .store.calls import CallLogRow
from .store.keys import KeyRow, NewKey
from .store.provider_keys import ProviderKeyRow
from .store.providers import NewProvider, ProviderBinding, ProviderRow


class _Wire(In):
    """A request body: camelCase on the wire, snake_case accepted, an unknown field refused."""


# The wire name of each field connection_problem names.
_FIELD = {"endpoint": "baseUrl", "api_version": "apiVersion"}
log = get_logger("ops_models.app")


def connection_problem(
    entry: ProviderEntry | None, base_url: str | None, api_version: str | None, region: str | None
) -> str | None:
    """Why a connection of the registry type `entry` with these values cannot be called, naming the field; None when
    it can. The fields each type takes, and their form, are its registry entry's; Azure's endpoint and api-version
    rule is the install settings' own (`connection_settings.azure_openai_problem`)."""
    if entry is None:
        return "type is not a provider type this install serves (GET /v1/models/provider-types lists them)"
    if entry.adapter == "azure-openai":
        problem = azure_openai_problem(base_url, api_version)
        if problem:
            return f"{_FIELD[problem[0]]} {problem[1]}"
    return entry.problem({"baseUrl": base_url, "apiVersion": api_version, "region": region})


class ProviderIn(_Wire):
    name: str = Field(min_length=1, max_length=120)
    # A provider type's id from the registry (GET /v1/models/provider-types).
    type: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,31}$")
    base_url: str | None = Field(default=None, max_length=400)
    key_ref: str | None = Field(default=None, pattern="^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
    api_version: str | None = Field(default=None, max_length=32)
    region: str | None = Field(default=None, max_length=64)
    # The type's secret fields (its x-secret ones), saved sealed as the account's provider key `keyRef` names and
    # never returned. Left out, the connection signs in with a key saved under that name before or after.
    secrets: dict[str, Annotated[str, Field(min_length=1, max_length=4000)]] | None = Field(default=None, max_length=8)

    @model_validator(mode="after")
    def _keyed(self) -> ProviderIn:
        if self.secrets and not self.key_ref:
            raise ValueError("keyRef is missing: the name the connection's secrets are saved under")
        return self


class ProviderRebind(_Wire):
    base_url: str = Field(min_length=1, max_length=400)
    key_ref: str | None = Field(default=None, max_length=120)
    api_version: str | None = Field(default=None, max_length=32)
    region: str | None = Field(default=None, max_length=64)


class ProviderKeyIn(_Wire):
    value: str = Field(min_length=1, max_length=4000)


class KeyCheckIn(_Wire):
    """Which provider the key is for, and for Azure OpenAI the resource's endpoint and API version."""

    # A provider type's id from the registry.
    provider: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,31}$")
    # The connection's base URL when it has its own (Azure OpenAI's resource, an OpenAI-compatible endpoint); a type
    # with a fixed address (OpenAI, Anthropic, Gemini) uses its own when this is left out.
    endpoint: str | None = Field(default=None, max_length=500)
    api_version: str | None = Field(default=None, max_length=40, pattern=r"^[0-9a-z-]+$")
    # Bedrock: the AWS region whose models are listed.
    region: str | None = Field(default=None, max_length=64)


class KeyCheckOut(Out):
    ok: bool
    reason: str | None = None
    models: int = 0


class ProviderModelOut(Out):
    id: str
    model: str | None = None


class ChatModelIn(_Wire):
    """The model chat answers with: a provider, the saved key it signs in with, and one of the models (or Azure
    deployments) that key lists."""

    provider: Literal["openai", "azure-openai", "anthropic"]
    key_name: str = Field(pattern="^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")
    model: str = Field(min_length=1, max_length=200)
    endpoint: str | None = Field(default=None, max_length=500)
    api_version: str | None = Field(default=None, max_length=40, pattern=r"^[0-9a-z-]+$")
    # Dollars per million tokens, for a model the catalog does not price (an Azure deployment); a catalogued model
    # takes the catalog's price when these are left out.
    input_per_million: Decimal | None = Field(default=None, ge=0)
    output_per_million: Decimal | None = Field(default=None, ge=0)


class ChatModelOut(Out):
    provider_id: str
    model: str
    aliases: list[str]


# Where each provider's chat calls go. Anthropic is served through its OpenAI-compatible endpoint, which takes the key
# as a bearer token, so the OpenAI-compatible client serves it with no client of its own.
CHAT_BASES = {"openai": "https://api.openai.com/v1", "anthropic": "https://api.anthropic.com/v1"}


# The name a provider connection's `key_ref` gives: `OPENAI`, or `openai` as the dev stack names it.
KEY_NAME = Path(pattern="^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")


class AliasVersionIn(_Wire):
    provider_id: str
    model_id: str
    cleared_sensitivity: str = Field(pattern="^(public|internal|confidential|restricted)$")
    # Both or neither: with neither, the catalog's price for the model; a model it does not price is refused.
    input_per_million: Decimal | None = Field(default=None, ge=0)
    output_per_million: Decimal | None = Field(default=None, ge=0)
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


INVALID_KEY = "The model key is unknown, or a rotated secret past its overlap."


async def model_key(authorization: Annotated[str | None, Header()] = None) -> str:
    """The model key a completion or an embedding authenticates with, from its `Authorization` header as OpenAI
    clients send it; 401 invalid_key when none is sent. The gate looks the key up in its one transaction and answers
    the same 401 for a key it does not know."""
    presented = (authorization or "").removeprefix("Bearer ").strip()
    if not presented:
        raise Unauthorized(INVALID_KEY, code="invalid_key")
    return presented


def refusal(status: int, code: str, message: str) -> ApiError:
    """A refusal a route raises, rendered by the kit's handler."""
    error = ApiError(message, code=code)
    error.status = status
    return error


def refused(status: int, code: str, message: str) -> JSONResponse:
    """A refusal returned rather than raised, by a model call whose call-log row must commit with it: the kit's error
    body, as the handler would render it."""
    return JSONResponse(error_body(status, code, message), status_code=status)


def provider_refused(e: ProviderError) -> JSONResponse:
    """A provider's failure in the platform envelope, with the provider's Retry-After when it named one."""
    headers = {"Retry-After": e.retry_after} if e.retry_after else None
    return JSONResponse(error_body(e.status, e.code, e.message), status_code=e.status, headers=headers)


def typed(reply: Out | Sequence[Out], status: int = 200) -> JSONResponse:
    """A reply model in the success envelope, under its wire names."""
    if isinstance(reply, Out):
        return ok(reply.model_dump(by_alias=True), status)
    return ok([r.model_dump(by_alias=True) for r in reply], status)


class ServedVersion(TypedDict, total=False):
    """The alias version a call is served by, as its call-log columns; empty until the alias is resolved."""

    alias_version: int
    provider_model: str


def _tool_call(call: Json) -> ToolCall:
    """A provider's tool call in OpenAI's reply format; a key OpenAI's format does not name is not passed on."""
    found = call.get("function")
    function = an_object(found, "tool call function") if found else {}
    named = ToolFunction(name=str(function.get("name") or ""), arguments=str(function.get("arguments") or ""))
    return ToolCall(id=str(call.get("id") or ""), type="function", function=named)


def _iso(v: datetime | None) -> str | None:
    return v.isoformat() if v is not None else None


def _key_view(r: KeyRow) -> KeyOut:
    return KeyOut(
        id=r.id,
        kind=r.kind,
        budget=str(r.budget),
        spent=str(r.spent),
        rate_limit_per_minute=r.rate_limit_per_minute,
        expires_at=_iso(r.expires_at),
        status=r.status,
        rotated_at=_iso(r.rotated_at),
        previous_valid_until=_iso(r.previous_valid_until),
    )


def _alias_view(r: AliasRow) -> AliasOut:
    return AliasOut(
        name=r.name,
        version=r.version,
        kind=r.kind,
        provider_id=r.provider_id,
        model_id=r.model_id,
        cleared_sensitivity=r.cleared_sensitivity,
        input_per_million=str(r.input_per_million),
        output_per_million=str(r.output_per_million),
        status=r.status,
        reasoning_effort=r.reasoning_effort,
        images=r.images,
    )


def _provider_view(r: ProviderRow) -> ProviderOut:
    return ProviderOut(
        id=r.id,
        name=r.name,
        type=r.type,
        base_url=r.base_url,
        key_ref=r.key_ref,
        api_version=r.api_version,
        region=r.region,
        observed_region=r.observed_region,
        region_mismatch=region_mismatch(r.observed_region, r.region),
    )


def _type_view(e: ProviderEntry) -> ProviderTypeOut:
    return ProviderTypeOut(
        id=e.id,
        label=e.label,
        icon=e.icon,
        connection=e.schema_view,
        lists_models=e.test != "none" and e.model_list is not None,
        catalogued=e.catalog is not None,
    )


def _catalog_view(model_id: str, m: CatalogModel, knobs: list[str]) -> CatalogModelOut:
    return CatalogModelOut(
        id=model_id,
        name=m.name,
        context=m.context,
        output=m.output,
        reasoning=m.reasoning,
        images=m.images,
        input_per_million=m.input_per_million,
        output_per_million=m.output_per_million,
        knobs=knobs,
    )


def _provider_key_view(r: ProviderKeyRow) -> ProviderKeyOut:
    return ProviderKeyOut(
        name=r.name,
        version=r.version,
        created_by=r.created_by,
        created_at=r.created_at.isoformat(),
        rotated_at=_iso(r.rotated_at),
    )


# A model call's charge, as the settle writes it and `recovery` replays it from a log line. Each write that names a
# tenant is made in that tenant's scope here, the one place models-service enters one for a call's spend.


class LostChargeLine(TypedDict):
    """What a log line of a charge nothing recorded carries: every field a replay needs, and the call, key and tenant
    to find it by."""

    call_id: str
    key_id: str
    tenant_id: str | None
    cost: Decimal
    per_tenant: bool
    at: datetime
    row: CallLogRow


class Charge(BaseModel):
    """One call's charge: its call-log row (the id is the settle's one id), whether the key spends per tenant, and
    when the provider answered."""

    model_config = ConfigDict(frozen=True)

    row: CallLogRow
    per_tenant: bool
    at: datetime

    def logged(self) -> LostChargeLine:
        row = self.row
        return LostChargeLine(
            call_id=row["id"],
            key_id=row["key_id"],
            tenant_id=row["tenant_id"],
            cost=row["cost"],
            per_tenant=self.per_tenant,
            at=self.at,
            row=row,
        )


async def charge(keys: ModelKeys, calls: CallLog, call: Charge, *, once: bool = False) -> bool:
    """The call's row, the period totals its caps read, the key's spent total and the tenant's share, in the open
    transaction: every ledger records the cost together or none does. With `once` (a replay), False and nothing
    written when the call's id already has its row."""
    if not once:
        # A settle takes the key's row first, then the period rows, as every instance of the service does.
        await _spend(keys, call)
        await _record(calls, call, once=False)
        return True
    # A replay writes the row first, so a call already charged adds no spend; replays are rare and one at a time.
    if not await _record(calls, call, once=True):
        return False
    await _spend(keys, call)
    return True


async def _spend(keys: ModelKeys, call: Charge) -> None:
    row, tenant = call.row, call.row["tenant_id"]
    if call.per_tenant and tenant:
        with isolation.scope(tenant, None):
            await keys.spend(row["key_id"], row["cost"], tenant_id=tenant)
    else:
        await keys.spend(row["key_id"], row["cost"])


async def _record(calls: CallLog, call: Charge, *, once: bool) -> bool:
    tenant = call.row["tenant_id"]
    if tenant:
        with isolation.scope(tenant, None):
            return await calls.record(call.row, at=call.at, once=once)
    return await calls.record(call.row, at=call.at, once=once)


def _key_refusal(key: KeyRow, now: datetime) -> tuple[int, str, str] | None:
    """Why a key may not spend right now: revoked, expired or at its budget. None when it may."""
    if key.status != "active":
        return 403, "key_revoked", f"Model key {key.id} is revoked."
    if key.expires_at is not None and key.expires_at <= now:
        return 403, "key_expired", f"Model key {key.id} expired at {key.expires_at.isoformat()}."
    if key.spent >= key.budget:
        return 429, "key_budget_exhausted", f"Model key {key.id} has spent its budget of {key.budget}."
    return None


def create_models_app(
    db: Database,
    *,
    auth: Auth | None = None,
    provider_secrets: Mapping[str, str] | None = None,
    overlap_seconds: int = 900,
    upstream: httpx.AsyncClient | None = None,
    credentials: CredentialStore | None = None,
    key_fetch: PublicFetch | None = None,
    chat_aliases: tuple[str, ...] = ("default", "assistant"),
    background: Sequence[Callable[[], Coroutine[Any, Any, None]]] | None = None,
    alias_users: AliasUsers | None = None,
) -> FastAPI:
    """Tests inject `upstream`, the client provider calls go out on; otherwise one is opened and closed with the app.
    `auth` resolves callers (ops_identity's shared dependency); by default it is built from Settings for "models".
    Provider keys are the accounts' own (`provider_keys`), kept in `credentials` (the store the settings choose by
    default); `provider_secrets` are the dev stack's keys from settings, behind them. `background` are the processes
    the lifespan runs beside the server, by default the sweep of idle key spend. `alias_users` says how many agents
    name each alias; by default agents-service on `OPS_AGENTS_URL`, and no counts when that is unset."""
    http = upstream or httpx.AsyncClient(timeout=60)

    stop = asyncio.Event()
    providers, aliases, key_store, call_log = Providers(db), Aliases(db), ModelKeys(db), CallLog(db)
    loops = background if background is not None else [lambda: call_log.spend.keep_sweeping(stop)]

    async def kept(start: Callable[[], Coroutine[Any, Any, None]]) -> None:
        # Each process reports its own failures on /health/background; one that still escapes is logged here, so it
        # never cancels the group, which would stop the server and the other processes with it.
        try:
            await start()
        except Exception as e:
            log.warning("models_background_stopped", error=f"{type(e).__name__}: {e}"[:500])

    # Settles still writing what a provider charged, each with the charge to log if the stop cannot wait for it.
    settling: dict[asyncio.Task[None], Charge] = {}

    async def drain_settles() -> None:
        """Waits for the settles in flight, at most as long as a request waits for a database connection: a settle
        that has no connection by then would fail anyway. One still unfinished is logged with its usage."""
        if not settling:
            return
        _, unfinished = await asyncio.wait(set(settling), timeout=settings.db.wait_s)
        for task in unfinished:
            log.error("model_call_settle_unfinished_at_stop", **settling[task].logged())

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(kept(start)) for start in loops]
            try:
                yield
            finally:
                await drain_settles()
                stop.set()
                for task in tasks:
                    task.cancel()
        if upstream is None:
            await http.aclose()
        if agents_client is not None:
            await agents_client.aclose()

    app = FastAPI(
        title="Ops AI models service",
        version="0.1.0",
        lifespan=lifespan,
        generate_unique_id_function=operation_id,
    )
    install_error_handlers(app)
    settings = Settings()
    # Testing a key sends it out: only to a public address, never following a redirect with it. In dev the fake OpenAI
    # the stack runs beside is the one address reached as it is (settings refuse the URL outside dev).
    fake = urlsplit(settings.models_fake_openai_url or "").netloc.lower()
    key_fetch = key_fetch or PublicFetch(max_redirects=0, timeout_s=20, local=(fake,) if fake else ())
    # Read and checked here, at start-up: an entry naming an adapter no code registers stops the service.
    registry = load_registry(ADAPTERS, BUILTIN, settings.models_provider_registry_extra)
    catalog = Catalog.load()
    agents_client: ServiceClient | None = None
    if alias_users is None:
        if settings.agents is not None:
            agents_client = ServiceClient.for_settings(
                settings, service="models", audience="agents", scopes=["agents:view"]
            )
        alias_users = AgentsAliasUsers(agents_client) if agents_client else NoAliasUsers()
    users: AliasUsers = alias_users
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

    # The /v1/models/* routes under `guard` take only a calling service's Ed25519 token: a person's token, an API key or
    # none is refused with 401 before the route runs, so no person's permission is decided here. A route a person
    # calls (provider connections, provider keys) takes the tenant caller and asks can(), as `connections_caller`.
    guard = Depends(current_service)

    async def connections_caller(p: CurrentTenantCaller) -> Principal:
        """Provider connections are set up by an install's own scripts (a service token) or by an account admin on
        Settings > Model providers (settings.manage, as for provider keys): one API for both."""
        if p.kind != "service":
            access.can(p, "settings", "manage", what="model provider connections", code="admin_only")
        return p

    connections_guard = Depends(connections_caller)

    async def alias_writer(p: CurrentTenantCaller) -> Principal:
        """Aliases are install-wide (one install serves one account): every team's agents run on them, so a person
        creates or re-points one only with `install.manage`, which Owner holds and a workspace Admin does not. An
        install's own scripts (a service token) write them as before."""
        if p.kind != "service":
            access.can(p, "install", "manage", what="the install's model aliases", code="install_admin_only")
        return p

    alias_write_guard = Depends(alias_writer)

    @app.get("/health", tags=["health"], response_model=Health)
    async def health() -> Health:  # pyright: ignore[reportUnusedFunction]
        return Health(status="ok")

    @app.get("/health/background", tags=["health"], response_model=BackgroundHealthOut)
    async def health_background() -> BackgroundHealthOut:  # pyright: ignore[reportUnusedFunction]
        """This service's background processes and their state; counts and error types only, no record's data."""
        listed = background_report(await LOCAL_BEATS.read(), "models", time.time())
        return BackgroundHealthOut.model_validate({"processes": listed})

    connection_errors = error_responses({400: "A value the connection's type refuses", 403: "Not an account admin"})

    @app.get(
        "/v1/models/providers",
        dependencies=[connections_guard],
        tags=["providers"],
        response_model=Envelope[ListResult[ProviderOut]],
        responses=connection_errors,
    )
    async def list_providers(_: Tx, q: ListQuery) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The provider connections by name: where their calls go and the name of the key each signs in with, never
        a key. `search` matches the name or the type; `ids` names connections by id."""
        page = await providers.page(q)
        views = [_provider_view(r) for r in page.data]
        return typed(ListResult[ProviderOut](data=views, pagination=page.pagination, facets=page.facets))

    @app.post(
        "/v1/models/providers",
        dependencies=[connections_guard],
        tags=["providers"],
        status_code=201,
        response_model=Envelope[ProviderCreated],
        responses=connection_errors,
    )
    async def create_provider(body: ProviderIn, p: CurrentTenantCaller, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Adds a connection of a registry type; 400 naming the field its type refuses (an Azure OpenAI connection
        needs its endpoint and api-version; a Bedrock one its region). `secrets` are saved as the account's provider
        key `keyRef` names, one value for a type with one secret field, else a JSON object of them."""
        entry = registry.get(body.type)
        if (why := connection_problem(entry, body.base_url, body.api_version, body.region)) is not None:
            raise ValidationFailed(why)
        assert entry is not None
        if body.secrets is not None:
            # Saving a key value is an account admin's, whoever calls: the rule PUT /v1/provider-keys/{name} holds to.
            account_admin(p)
            # New secrets under a name another connection signs in with would change that connection's key unseen.
            using = [r.name for r in (await providers.page(ListParams(), key_ref=body.key_ref)).data]
            if using:
                raise Conflict(
                    f"Provider connection {', '.join(using)} signs in with key {body.key_ref}; name another key, or "
                    "leave secrets out to share it.",
                    code="key_ref_in_use",
                )
            wanted = entry.secret_fields
            if set(body.secrets) != set(wanted):
                raise ValidationFailed(f"secrets are {', '.join(wanted) or 'none'} for {entry.label} connections")
            value = body.secrets[wanted[0]] if len(wanted) == 1 else json.dumps(body.secrets, sort_keys=True)
            await key_vault.save(p.tenant_id, str(body.key_ref), value, by=p.email or p.sub)
            keys.forget(p.tenant_id, str(body.key_ref))
        pid = new_id("prov")
        row: NewProvider = {
            "id": pid,
            "name": body.name,
            "type": body.type,
            "base_url": body.base_url,
            "key_ref": body.key_ref,
            "api_version": body.api_version,
            "region": body.region,
            "created_at": now_iso(),
        }
        if not await providers.create(row):
            raise Conflict(f"A provider connection named {body.name} exists.", code="provider_exists")
        return typed(ProviderCreated(id=pid, name=body.name, type=body.type), status=201)

    def provider_type(type_id: str) -> ProviderEntry:
        entry = registry.get(type_id)
        if entry is None:
            raise ValidationFailed(f"provider {type_id} is not a provider type this install serves")
        return entry

    @app.get(
        "/v1/models/provider-types",
        dependencies=[connections_guard],
        tags=["providers"],
        response_model=Envelope[list[ProviderTypeOut]],
        responses=connection_errors,
    )
    async def list_provider_types() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The provider types a connection can be made of, by label: the fields each takes as a JSON Schema (an
        `x-secret` field is saved as a provider key and never returned), and whether its models can be listed and are
        in the model catalog."""
        return typed([_type_view(e) for e in registry.listed()])

    @app.get(
        "/v1/models/providers/{provider_id}/catalog",
        dependencies=[connections_guard],
        tags=["providers"],
        response_model=Envelope[list[CatalogModelOut]],
        responses=error_responses({403: "Not an account admin", 404: "No such connection"}),
    )
    async def list_catalog_models(provider_id: str, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The catalogued models of the connection's provider type, by id, each with its context, output limit, prices
        and the knobs it takes; empty for a type the catalog does not hold (an OpenAI-compatible URL)."""
        row = await providers.get(provider_id)
        if row is None:
            raise refusal(404, "provider_not_found", f"No provider connection {provider_id}.")
        entry = registry.get(row.type)
        kind = entry.catalog if entry else None
        return typed([_catalog_view(i, m, sorted(catalog.ranges_for(kind, m))) for i, m in catalog.listed(kind)])

    @app.put(
        "/v1/models/providers/{provider_id}",
        dependencies=[connections_guard],
        tags=["providers"],
        response_model=Envelope[ProviderOut],
        responses=connection_errors,
    )
    async def rebind_provider(provider_id: str, body: ProviderRebind, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Points a connection at another endpoint, credential name, api-version and region. Every alias version bound
        to it follows on its next call, which is how one alias moves between a fake and the real provider without a
        new version."""
        row = await providers.get(provider_id)
        if row is None:
            raise refusal(404, "provider_not_found", f"No provider connection {provider_id}.")
        # A connection's type never changes after it is made, so the check holds without a lock.
        if row.type == "scripted":
            raise Conflict("A scripted connection has no endpoint to change.", code="provider_not_rebindable")
        # An api-version or region left out keeps the stored one: the install scripts move only the base URL and key.
        given = body.model_fields_set
        version = body.api_version if "api_version" in given else row.api_version
        region = body.region if "region" in given else row.region
        if (why := connection_problem(registry.get(row.type), body.base_url, version, region)) is not None:
            raise ValidationFailed(why)
        fields: ProviderBinding = {
            "base_url": body.base_url,
            "key_ref": body.key_ref,
            "api_version": version,
            "region": region,
        }
        await providers.rebind(provider_id, fields)
        return typed(_provider_view(row.model_copy(update={**fields, "observed_region": None})))

    def account_admin(p: CurrentPrincipal) -> str:
        """settings.manage, held in the Security team: an account admin. Returns the actor."""
        access.can(p, "settings", "manage", what="model provider keys", code="admin_only")
        return p.email or p.sub

    key_errors = error_responses({403: "Not an account admin", 409: "A provider connection still uses the key"})

    @app.get(
        "/v1/provider-keys",
        tags=["provider-keys"],
        response_model=Envelope[ListResult[ProviderKeyOut]],
        responses=key_errors,
    )
    async def list_provider_keys(p: CurrentPrincipal, _: Tx, q: ListQuery) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The account's model provider keys by name; a value is never returned. `search` and `ids` match the name."""
        account_admin(p)
        page = await key_vault.page(p.tenant_id, q)
        views = [_provider_key_view(r) for r in page.data]
        return typed(ListResult[ProviderKeyOut](data=views, pagination=page.pagination, facets=page.facets))

    @app.put(
        "/v1/provider-keys/{name}",
        tags=["provider-keys"],
        response_model=Envelope[ProviderKeyOut],
        responses=key_errors,
    )
    async def save_provider_key(  # pyright: ignore[reportUnusedFunction]
        name: Annotated[str, KEY_NAME], body: ProviderKeyIn, p: CurrentPrincipal, _: Tx
    ) -> JSONResponse:
        """Saves a key under the name a provider connection's keyRef gives, or replaces its value. The next call
        through a connection naming it uses the new value."""
        by = account_admin(p)
        saved, _new = await key_vault.save(p.tenant_id, name, body.value, by=by)
        keys.forget(p.tenant_id, name)
        return typed(_provider_key_view(saved))

    async def connection_base(provider: str, key_name: str) -> str | None:
        """The base URL of the connection that signs in with the key `key_name`, the one place a key check, a model
        list and the chat choice learn where a key goes: only a connection whose keyRef names the key receives it.
        None when no OpenAI-compatible connection does, so the provider's own address applies."""
        if provider not in CHAT_BASES:
            return None
        # A key name can serve two providers' connections; one pointing at another provider's own address is not this
        # provider's.
        others = {b for p, b in CHAT_BASES.items() if p != provider}
        named = (await providers.page(ListParams(), key_ref=key_name)).data
        return next(
            (r.base_url for r in named if r.type == "openai-compatible" and r.base_url and r.base_url not in others),
            None,
        )

    async def saved_key(p: Principal, name: str) -> str:
        """The key's value, read in a transaction of its own that is closed before the key goes to the provider; inside
        a route on `Tx` it is the request's."""
        account_admin(p)
        async with isolation.request_transaction():
            value = await keys.get(name, p.tenant_id)
        if value is None:
            raise NotFound(f"Model provider key {name}")
        return value

    @app.post(
        "/v1/provider-keys/{name}/check",
        tags=["provider-keys"],
        response_model=Envelope[KeyCheckOut],
        responses=error_responses({403: "Not an account admin", 404: "No key saved under that name"}),
    )
    async def check_provider_key(  # pyright: ignore[reportUnusedFunction]
        name: Annotated[str, KEY_NAME], body: KeyCheckIn, p: CurrentPrincipal
    ) -> JSONResponse:
        """Asks the provider for what the saved key reaches: ok with how many models or deployments, or not ok with
        the provider's reason. Nothing is called with the key otherwise."""
        entry = provider_type(body.provider)
        value = await saved_key(p, name)
        try:
            found = await listed_models(
                http,
                key_fetch,
                entry,
                value,
                endpoint=body.endpoint,
                api_version=body.api_version,
                region=body.region,
                connection_base=await connection_base(body.provider, name),
            )
        except KeyRefused as e:
            return typed(KeyCheckOut(ok=False, reason=str(e)))
        except EndpointRefused as e:
            raise Unprocessable(str(e), code="endpoint_refused") from e
        return typed(KeyCheckOut(ok=True, models=len(found)))

    @app.get(
        "/v1/provider-keys/{name}/models",
        tags=["provider-keys"],
        response_model=Envelope[list[ProviderModelOut]],
        responses=error_responses({403: "Not an account admin", 422: "The provider refused the key"}),
    )
    async def list_provider_models(  # pyright: ignore[reportUnusedFunction]
        *,
        name: Annotated[str, KEY_NAME],
        p: CurrentPrincipal,
        provider: Annotated[str, Query(pattern=r"^[a-z0-9][a-z0-9-]{1,31}$")],
        endpoint: Annotated[str | None, Query(max_length=500)] = None,
        api_version: Annotated[str | None, Query(alias="apiVersion", max_length=40, pattern=r"^[0-9a-z-]+$")] = None,
        region: Annotated[str | None, Query(max_length=64)] = None,
    ) -> JSONResponse:
        """The models (OpenAI, Anthropic, Gemini, Bedrock) or deployments (Azure OpenAI) the saved key reaches, for
        choosing which one an alias uses; 422 key_refused with the provider's reason."""
        entry = provider_type(provider)
        value = await saved_key(p, name)
        try:
            found = await listed_models(
                http,
                key_fetch,
                entry,
                value,
                endpoint=endpoint,
                api_version=api_version,
                region=region,
                connection_base=await connection_base(provider, name),
            )
        except KeyRefused as e:
            raise Unprocessable(str(e), code="key_refused") from e
        except EndpointRefused as e:
            raise Unprocessable(str(e), code="endpoint_refused") from e
        return ok(found)

    def known_price(
        catalog_id: str | None, model_id: str, given_in: Decimal | None, given_out: Decimal | None
    ) -> tuple[Decimal, Decimal]:
        """The price every alias version is written at, the one rule for it: both prices given, else the catalog's
        for the model. A version at zero lets every budget pass, so one price alone (422 `price_incomplete`), zero
        for a model the catalog does not list at zero, or no price at all (422 `price_required`) is refused."""
        if (given_in is None) != (given_out is None):
            raise Unprocessable(
                "Give both the input and the output price per million tokens, or neither for the catalog's.",
                code="price_incomplete",
            )
        found = catalog.model(catalog_id, model_id)
        listed = (
            None
            if found is None or found.input_per_million is None or found.output_per_million is None
            else (Decimal(str(found.input_per_million)), Decimal(str(found.output_per_million)))
        )
        if given_in is not None and given_out is not None:
            if given_in or given_out or listed == (0, 0):
                return given_in, given_out
            raise Unprocessable(
                f"A price of zero lets every budget pass, and the model catalog does not list {model_id} as free; give "
                "its input and output price per million tokens.",
                code="price_required",
            )
        if listed is not None:
            return listed
        raise Unprocessable(
            f"{model_id} has no price in the model catalog; give its input and output price per million tokens.",
            code="price_required",
        )

    async def version_price(body: AliasVersionIn) -> tuple[Decimal, Decimal]:
        connection = await providers.get(body.provider_id)
        catalog_id = registry.catalog_for(connection.type, connection.base_url) if connection else None
        return known_price(catalog_id, body.model_id, body.input_per_million, body.output_per_million)

    @app.put(
        "/v1/models/chat-model",
        tags=["providers"],
        response_model=Envelope[ChatModelOut],
        responses=error_responses(
            {
                403: "Not an account admin",
                404: "No key saved under that name",
                422: "The endpoint is refused, or the chat model has no known price",
            }
        ),
    )
    async def set_chat_model(body: ChatModelIn, p: CurrentPrincipal, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Points chat (the runtime's `default` alias and the team assistant's) at `model` on the provider the saved key
        belongs to. One connection per provider is kept and moved on a later choice; each alias gets a new version, or
        version 1 on a fresh install, where no chat alias exists yet. The chat aliases are the install's, so this
        also needs `install.manage` (403 `install_admin_only`)."""
        await saved_key(p, body.key_name)
        await alias_writer(p)
        if body.provider == "azure-openai":
            try:
                base = azure_host(body.endpoint)
            except EndpointRefused as e:
                raise Unprocessable(str(e), code="endpoint_refused") from e
            kind, base_url, api_version = "azure-openai", base, body.api_version or "v1"
        else:
            kind, api_version = "openai-compatible", None
            base_url = await connection_base(body.provider, body.key_name) or CHAT_BASES[body.provider]
        # Every price is settled before anything is written. An alias kept on the same model keeps its nonzero prices,
        # which an admin may have set on the Models page; a body price, or a new model, sets them.
        # Priced by the provider's catalogue, whatever address its connection calls: a gateway in front of OpenAI
        # serves OpenAI's models.
        catalog_id = registry.catalog_for(kind, CHAT_BASES.get(body.provider, base_url))
        given = body.input_per_million is not None or body.output_per_million is not None
        prices: dict[str, tuple[Decimal, Decimal]] = {}
        fresh: set[str] = set()
        for alias in chat_aliases:
            serving = await aliases.current(alias)
            if serving is None:
                fresh.add(alias)
            kept = serving is not None and serving.model_id == body.model and not given
            if kept and serving is not None and (serving.input_per_million or serving.output_per_million):
                prices[alias] = (serving.input_per_million, serving.output_per_million)
            else:
                prices[alias] = known_price(catalog_id, body.model, body.input_per_million, body.output_per_million)
        name = f"{chat_aliases[0]}-{body.provider}"
        held = next(iter((await providers.page(ListParams(), name=name)).data), None)
        pid = new_id("prov") if held is None else held.id
        if held is None and not await providers.create(
            {
                "id": pid,
                "name": name,
                "type": kind,
                "base_url": base_url,
                "key_ref": body.key_name,
                "api_version": api_version,
                "region": None,
                "created_at": now_iso(),
            }
        ):
            held = (await providers.page(ListParams(), name=name)).data[0]
        if held is not None:
            pid = held.id
            await providers.rebind(
                pid, {"base_url": base_url, "key_ref": body.key_name, "api_version": api_version, "region": None}
            )
        for alias in chat_aliases:
            fields: AliasFields = {
                "provider_id": pid,
                "model_id": body.model,
                "cleared_sensitivity": "confidential",
                "input_per_million": prices[alias][0],
                "output_per_million": prices[alias][1],
                "reasoning_effort": None,
                "images": False,
            }
            if alias in fresh or await aliases.add_version(alias, fields) is None:
                await aliases.create(alias, "chat", fields)
        return typed(ChatModelOut(provider_id=pid, model=body.model, aliases=list(chat_aliases)))

    @app.delete(
        "/v1/provider-keys/{name}",
        tags=["provider-keys"],
        status_code=204,
        response_class=Response,
        responses=key_errors,
    )
    async def delete_provider_key(name: Annotated[str, KEY_NAME], p: CurrentPrincipal, _: Tx) -> Response:  # pyright: ignore[reportUnusedFunction]
        """Deletes a key no provider connection names; 409 naming the connection that still does."""
        account_admin(p)
        using = [r.name for r in (await providers.page(ListParams(), key_ref=name)).data]
        if using:
            raise Conflict(f"Provider connection {', '.join(using)} signs in with {name}.", code="key_in_use")
        if not await key_vault.delete(p.tenant_id, name):
            raise NotFound(f"Model provider key {name}")
        keys.forget(p.tenant_id, name)
        return Response(status_code=204)

    async def named(rows: Sequence[AliasRow], caller: Principal) -> list[AliasOut]:
        """Each alias version with its connection's name, read in one page of connections by id, and for a person how
        many agents name the alias (agents-service, one call per page). A service reads the list to resolve aliases
        and gets no count, so agents-service's own alias reads never call it back."""
        ids = sorted({r.provider_id for r in rows})
        held = (await providers.page(ListParams(ids=ids, page_size=len(ids)))).data if ids else []
        names = {c.id: c.name for c in held}
        wanted = sorted({r.name for r in rows}) if caller.kind == "person" else []
        used = await users.counts(caller.tenant_id, wanted) if wanted else {}
        return [
            _alias_view(r).model_copy(update={"provider_name": names.get(r.provider_id), "used_by": used.get(r.name)})
            for r in rows
        ]

    @app.get(
        "/v1/models/aliases",
        dependencies=[connections_guard],
        tags=["aliases"],
        response_model=Envelope[ListResult[AliasOut]],
        responses=ERRORS,
    )
    async def list_aliases(caller: CurrentTenantCaller, _: Tx, q: ListQuery) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Each alias's serving version, by name. `search` matches the name, the kind or the model; `ids` names
        aliases by name. `usedBy`: how many agents name the alias, for a person; null for a service or when
        agents-service did not answer."""
        page = await aliases.page(q)
        views = await named(page.data, caller)
        return typed(ListResult[AliasOut](data=views, pagination=page.pagination, facets=page.facets))

    @app.post(
        "/v1/models/aliases",
        dependencies=[alias_write_guard],
        tags=["aliases"],
        status_code=201,
        response_model=Envelope[AliasRef],
        responses=ERRORS,
    )
    async def create_alias(body: AliasIn, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        if not await aliases.create(body.name, body.kind, _version_fields(body, await version_price(body))):
            raise Conflict(f"Alias {body.name} exists; add a version instead.", code="alias_exists")
        return typed(AliasRef(name=body.name, version=1), status=201)

    @app.get(
        "/v1/models/aliases/{name}/versions",
        dependencies=[connections_guard],
        tags=["aliases"],
        response_model=Envelope[ListResult[AliasOut]],
        responses=ERRORS,
    )
    async def list_versions(name: str, caller: CurrentTenantCaller, _: Tx, q: ListQuery) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The alias's versions, oldest first. `search` matches the model or the status; `ids` names versions by
        number. 404 when there is no such alias."""
        page = await aliases.version_page(name, q)
        if page is None:
            raise refusal(404, "alias_not_found", f"No alias {name}.")
        views = await named(page.data, caller)
        return typed(ListResult[AliasOut](data=views, pagination=page.pagination, facets=page.facets))

    @app.get(
        "/v1/models/aliases/{name}/knobs",
        dependencies=[connections_guard],
        tags=["aliases"],
        response_model=Envelope[KnobsOut],
        responses=ERRORS,
    )
    async def alias_knobs(name: str, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The settings an agent on this alias may set, as a JSON Schema object: only the knobs its model takes, each
        with its range and catalog default. A model the catalog does not hold gets the common knobs with no range;
        404 when there is no such alias."""
        held = await aliases.current(name)
        if held is None:
            raise refusal(404, "alias_not_found", f"No alias {name}.")
        connection = await providers.get(held.provider_id)
        entry = registry.get(connection.type) if connection else None
        schema = catalog.knob_schema(entry.catalog if entry else None, held.model_id)
        return typed(
            KnobsOut(
                alias=name,
                version=held.version,
                model_id=held.model_id,
                catalogued=bool(schema["x-catalogued"]),
                knobs=schema,
            )
        )

    @app.post(
        "/v1/models/aliases/{name}/versions",
        dependencies=[alias_write_guard],
        tags=["aliases"],
        status_code=201,
        response_model=Envelope[AliasRef],
        responses=ERRORS,
    )
    async def add_version(name: str, body: AliasVersionIn, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        # Versions are immutable: a change is a new version, which replaces the one serving.
        if await aliases.current(name) is None:
            raise refusal(404, "alias_not_found", f"No alias {name}.")
        version = await aliases.add_version(name, _version_fields(body, await version_price(body)))
        if version is None:
            raise refusal(404, "alias_not_found", f"No alias {name}.")
        return typed(AliasRef(name=name, version=version), status=201)

    @app.get(
        "/v1/models/keys",
        dependencies=[guard],
        tags=["keys"],
        response_model=Envelope[ListResult[KeyOut]],
        responses=ERRORS,
    )
    async def list_keys(_: Tx, q: ListQuery) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The model keys by id, never a secret or its hash. `search` matches the id, the kind or the status; `ids`
        names keys by id."""
        page = await key_store.page(q)
        views = [_key_view(r) for r in page.data]
        return typed(ListResult[KeyOut](data=views, pagination=page.pagination, facets=page.facets))

    @app.post(
        "/v1/models/keys",
        dependencies=[guard],
        tags=["keys"],
        status_code=201,
        response_model=Envelope[KeySecret],
        responses=ERRORS,
    )
    async def issue_key(body: KeyIn, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        secret = new_secret()
        issued: NewKey = {
            "id": body.id,
            "kind": body.kind,
            "budget": body.budget,
            "spent": Decimal(0),
            "status": "active",
            "rate_limit_per_minute": body.rate_limit_per_minute,
            "expires_at": body.expires_at,
            "secret_hash": secret_hash(secret),
        }
        if not await key_store.issue(issued):
            raise Conflict(f"A key for {body.id} exists; rotate it instead.", code="key_exists")
        # The secret is returned once and stored only as a hash.
        return typed(KeySecret(id=body.id, secret=secret), status=201)

    @app.post(
        "/v1/models/keys/{key_id}/rotate",
        dependencies=[guard],
        tags=["keys"],
        response_model=Envelope[KeyRotated],
        responses=ERRORS,
    )
    async def rotate_key(key_id: str, body: RotateIn, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        secret = new_secret()
        overlap = body.overlap_seconds if body.overlap_seconds is not None else overlap_seconds
        now = datetime.now(UTC)
        if not await key_store.rotate(key_id, secret_hash(secret), now + timedelta(seconds=overlap), now):
            raise refusal(404, "key_not_found", f"No key {key_id}.")
        until = (now + timedelta(seconds=overlap)).isoformat()
        return typed(KeyRotated(id=key_id, secret=secret, previous_valid_until=until))

    @app.get(
        "/v1/models/calls", dependencies=[guard], tags=["calls"], response_model=Envelope[CallPage], responses=ERRORS
    )
    async def list_calls(  # pyright: ignore[reportUnusedFunction]
        _: Tx,
        q: ListQuery,
        key_id: Annotated[str | None, Query(alias="keyId")] = None,
        alias: str | None = None,
        outcome: str | None = None,
        thread_id: Annotated[str | None, Query(alias="threadId")] = None,
    ) -> JSONResponse:
        """The tenant's calls, newest first (`sortBy=createdAt` with `sortOrder`), and `byKey`: per key, how many
        calls match and what they cost, across every page."""
        page = await call_log.page(q, key_id=key_id, alias=alias, outcome=outcome, thread_id=thread_id)
        items = [
            CallOut(
                id=r.id,
                key_id=r.key_id,
                alias=r.alias,
                alias_version=r.alias_version,
                provider_model=r.provider_model,
                input_tokens=r.input_tokens,
                output_tokens=r.output_tokens,
                cost=str(r.cost),
                latency_ms=r.latency_ms,
                outcome=r.outcome,
                reason=r.reason,
                run_id=r.run_id,
                step_id=r.step_id,
                thread_id=r.thread_id,
                request_hash=r.request_hash,
                created_at=_iso(r.created_at),
                images=r.images,
            )
            for r in page.data
        ]
        by_key = [KeySpend(key_id=t.key_id, calls=t.calls, cost=str(t.cost)) for t in page.by_key]
        return typed(CallPage(data=items, pagination=page.pagination, facets=page.facets, by_key=by_key))

    @app.post(
        "/v1/models/admit",
        dependencies=[guard],
        tags=["admission"],
        response_model=Envelope[Admission],
        responses=ERRORS,
    )
    async def admit(body: AdmitIn, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """agents-service asks before it opens a thread. An unregistered identity is refused: every caller that
        spends on models needs a key with a budget."""
        key = await key_store.get(body.key_id)
        if key is None:
            raise Forbidden(f"No model key is registered for {body.key_id}.", code="key_not_registered")
        if (why := _key_refusal(key, datetime.now(UTC))) is not None:
            raise refusal(*why)
        remaining: Decimal = key.budget - key.spent
        if body.alias and body.estimated_tokens:
            alias_row = await aliases.current(body.alias)
            if alias_row is not None:
                estimate = cost(Usage(input_tokens=body.estimated_tokens), Price(alias_row.input_per_million))
                if estimate > remaining:
                    raise TooManyRequests(
                        f"The estimate {estimate} exceeds {remaining} left.", code="key_budget_exhausted"
                    )
        return typed(Admission(admitted=True, remaining=str(remaining)))

    class Gate:
        """One authenticated call on its way to a provider: the key, the alias version it is served by, its price, and
        the one call-log row it writes, whether it is refused here, fails at the provider or settles."""

        def __init__(self, key: KeyRow, row: dict[str, str | int | None], tenant: str | None) -> None:
            self.key, self.row, self.tenant = key, row, tenant
            self.started = time.perf_counter()
            self.version: ServedVersion = {}
            self.alias_row: ServingAlias | None = None
            self.price = Price(Decimal(0))
            self.provider: Any = None

        def row_of(self, outcome: str, reason: str | None = None, **values: Any) -> CallLogRow:
            """The call's one row as it is written: a fresh id unless `values` names the settle's."""
            row = {
                "id": values.pop("id", None) or new_id("mc"),
                "input_tokens": values.pop("input_tokens", 0),
                "output_tokens": values.pop("output_tokens", 0),
                "cost": values.pop("cost", Decimal(0)),
                "latency_ms": int((time.perf_counter() - self.started) * 1000),
                "outcome": outcome,
                "reason": reason,
                **self.row,
                **values,
            }
            # The gate's row and the version name only call-log columns (`CallLogRow`).
            return cast(CallLogRow, row)

        async def log(self, outcome: str, reason: str | None = None, **values: Any) -> None:
            """The call's one row: the named tenant's, written as that tenant; a call that named none has no tenant's
            log to land in (`CallLog.record`)."""
            row = self.row_of(outcome, reason, **values)
            if self.tenant:
                with isolation.scope(self.tenant, None):
                    await call_log.record(row)
            else:
                await call_log.record(row)

        async def refuse(self, status: int, code: str, message: str, *, versioned: bool = True) -> JSONResponse:
            await self.log("error" if status >= 500 else "denied", code, **(self.version if versioned else {}))
            return refused(status, code, message)

        # After the provider answers, everything the call writes (the region it answered from, the spend, its row) is
        # one transaction of its own: none is open while the provider works, and the gate's committed before it.

        async def settle(self, input_tokens: int, output_tokens: int) -> None:
            """Records what the provider charged, in a task of its own: a client gone or a cancel after the answer
            does not roll it back. When neither the write nor its fallback lands, the whole charge is logged at error
            level, for `ops_models.recovery` to replay."""
            spend = cost(Usage(input_tokens=input_tokens, output_tokens=output_tokens), self.price)
            charged = {"input_tokens": input_tokens, "output_tokens": output_tokens, "cost": spend}
            # One id for the call's row whichever attempt or replay writes it, so one after a write that committed
            # fails on the row and adds no spend again.
            row = self.row_of("error", "settle_failed", id=new_id("mc"), **charged, **self.version)
            failed = Charge(row=row, per_tenant=self.key.tenant_budget is not None, at=datetime.now(UTC))
            task = asyncio.ensure_future(self._settle(failed))
            # Held until it ends, so the server's stop waits for it (`drain_settles`).
            settling[task] = failed
            task.add_done_callback(lambda done: settling.pop(done, None))
            await asyncio.shield(task)

        async def _settle(self, failed: Charge) -> None:
            # An Azure answer from another region than its connection names is recorded on the row, not refused.
            provider = self.provider
            mismatch = provider.region_mismatch if isinstance(provider, AzureOpenAIProvider) else None
            answered = failed.row.copy()
            answered["outcome"], answered["reason"] = "ok", mismatch[:64] if mismatch else None
            done = failed.model_copy(update={"row": answered})
            try:
                async with isolation.request_transaction():
                    await self.observed()
                    await charge(key_store, call_log, done)
            except Exception:
                row = failed.row
                log.exception(
                    "model_call_settle_failed",
                    call_id=row["id"],
                    key_id=self.key.id,
                    tenant_id=self.tenant,
                    alias=row["alias"],
                    provider_model=self.version.get("provider_model"),
                    input_tokens=row["input_tokens"],
                    output_tokens=row["output_tokens"],
                    cost=str(row["cost"]),
                )
                # The call keeps its one row, an error with what the provider charged, and every ledger its cost, in a
                # transaction of its own.
                try:
                    async with isolation.request_transaction():
                        await charge(key_store, call_log, failed)
                except Exception:
                    log.exception("model_call_row_lost", **failed.logged())
                raise

        async def broke(self, reason: str) -> None:
            """A stream that ended without settling: the provider failed part-way or the client went."""
            async with isolation.request_transaction():
                await self.observed()
                await self.log("error", reason, **self.version)

        async def observed(self) -> None:
            """Records the region an Azure resource answered from on its connection, when it changed."""
            provider = self.provider
            seen = provider.observed_region if isinstance(provider, AzureOpenAIProvider) else None
            alias = self.alias_row
            if seen and alias is not None and seen != alias.observed_region:
                await providers.observe(alias.provider_id, seen)

        async def failed(self, e: Exception) -> JSONResponse:
            """The provider's failure as the caller gets it, its code also the call-log row's reason."""
            failure = e if isinstance(e, ProviderError) else ProviderError(why="the provider answered an empty stream")
            await self.broke(failure.code)
            return provider_refused(failure)

        @property
        def serving(self) -> ServingAlias:
            """The alias version a gate that opened is served by."""
            if self.alias_row is None:
                raise RuntimeError("the gate has no alias version until open_gate sets it")
            return self.alias_row

    async def open_gate(
        presented: str,
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
        now = datetime.now(UTC)
        key = await key_store.by_secret(secret_hash(presented), now)
        if key is None:
            return refused(401, "invalid_key", INVALID_KEY)
        row_values = {"key_id": key.id, "alias": alias_name, "sensitivity": sensitivity, "tenant_id": tenant}
        gate = Gate(key, {**row_values, **row, "images": images}, tenant)
        if (why := _key_refusal(key, now)) is not None:
            return await gate.refuse(*why)
        if key.tenant_budget is not None:
            # A key one service spends for many tenants: the tenant names its own budget row.
            if not tenant:
                return await gate.refuse(
                    400, "tenant_required", f"Model key {key.id} spends per tenant; send X-Tenant-Id."
                )
            # The share is the named tenant's: read as that tenant, which the database holds the row to.
            with isolation.scope(tenant, None):
                share = await key_store.tenant_share(key.id, tenant, key.tenant_budget)
            if share.spent >= share.budget:
                return await gate.refuse(
                    429,
                    "tenant_budget_exhausted",
                    f"Tenant {tenant} has spent its budget of {share.budget} on model key {key.id}.",
                )
        # The key's caps are the key's, summed over every tenant it spends for, in one read.
        totals = await call_log.totals(key.id, now, run_id=row.get("run_id") if run_cap is not None else None)
        if key.daily_cap is not None and totals.today >= key.daily_cap:
            return await gate.refuse(
                429, "daily_spend_cap", f"Model key {key.id} has spent its {key.daily_cap} for today."
            )
        if run_cap is not None and row.get("run_id"):
            try:
                cap = Decimal(run_cap)
            except InvalidOperation:
                return await gate.refuse(400, "invalid_spend_cap", "X-Run-Spend-Cap is an amount, such as 5.00.")
            if totals.run >= cap:
                return await gate.refuse(
                    429, "run_spend_cap", f"Run {row['run_id']} has spent its {cap} on model key {key.id}."
                )
        recent = totals.recent
        alias_row = await aliases.current(alias_name)
        if recent >= key.rate_limit_per_minute:
            return await gate.refuse(
                429, "rate_limited", f"Model key {key.id} is over {key.rate_limit_per_minute} calls a minute."
            )
        if alias_row is None:
            return await gate.refuse(404, "alias_not_found", f"No current version of alias {alias_name}.")
        gate.alias_row = alias_row
        gate.version = {"alias_version": alias_row.version, "provider_model": alias_row.model_id}
        if alias_row.kind != kind:
            return await gate.refuse(
                400, "alias_kind_mismatch", f"Alias {alias_name} is a {alias_row.kind} alias, not {kind}."
            )
        if sensitivity not in SENSITIVITY or not cleared(alias_row.cleared_sensitivity, sensitivity):
            return await gate.refuse(
                403,
                "sensitivity_not_cleared",
                f"Alias {alias_name} is cleared for {alias_row.cleared_sensitivity} data, not {sensitivity}.",
            )
        if images and not alias_row.images:
            return await gate.refuse(
                403, "images_not_cleared", f"Alias {alias_name} is not cleared for images or files."
            )
        gate.price = Price(alias_row.input_per_million, alias_row.output_per_million)
        ref = alias_row.key_ref
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
            secrets_by_ref = {str(ref): provider_key} if ref and provider_key else {}
            gate.provider = provider_for(alias_row, secrets_by_ref, http, registry)
        except ProviderError as e:
            await gate.log("error", e.code)
            return provider_refused(e)
        return gate

    async def completions(
        request: ChatCompletionRequest,
        *,
        presented: Annotated[str, Depends(model_key)],
        x_data_sensitivity: Annotated[str, Header()] = "internal",
        x_run_id: Annotated[str | None, Header()] = None,
        x_step_id: Annotated[str | None, Header()] = None,
        x_thread_id: Annotated[str | None, Header()] = None,
        x_request_hash: Annotated[str | None, Header()] = None,
        x_tenant_id: Annotated[str | None, Header()] = None,
        x_run_spend_cap: Annotated[str | None, Header()] = None,
    ) -> ChatCompletion | Response:
        body = request.model_dump(exclude_unset=True)
        alias_name = request.model
        # The gate is one transaction, committed (a refusal's row with it) before the provider is called.
        async with isolation.request_transaction():
            gate = await open_gate(
                presented,
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
        alias_row, provider = gate.serving, gate.provider
        settle, broke, failed = gate.settle, gate.broke, gate.failed
        if alias_row.reasoning_effort and "reasoning_effort" not in body:
            body["reasoning_effort"] = alias_row.reasoning_effort
        served_type = registry.get(alias_row.type)
        body = catalog.fit(body, served_type.catalog if served_type else None, alias_row.model_id)
        call_id = new_id("chatcmpl")
        created = int(time.time())

        if request.stream:
            usage = StreamUsage()
            chunks = provider.stream(alias_row.model_id, body, usage)
            # The first chunk is read before answering, so a provider that refuses the request is a 502, not a 200
            # stream that ends early.
            try:
                first = await anext(chunks)
            except (ProviderError, StopAsyncIteration) as e:
                return await failed(e)

            async def events() -> AsyncIterator[str]:
                settled = False
                reason = "provider_error"
                try:
                    pending: Json | None = first
                    while pending is not None:
                        out = {**pending, "id": call_id, "created": created, "model": alias_name}
                        yield f"data: {json.dumps(out)}\n\n"
                        pending = await anext(chunks, None)
                    # Spend and the log row are written before the client sees the end: once it has [DONE] it
                    # disconnects, and Starlette cancels whatever this generator is still awaiting. The settle is
                    # shielded, so it runs to its end even then, and writes the call's row whether it succeeds or
                    # fails: marked settled before it starts, so a cancel or its failure adds no second row.
                    settled = True
                    await settle(usage.input_tokens, usage.output_tokens)
                    yield "data: [DONE]\n\n"
                except ProviderError as e:
                    reason = e.code
                finally:
                    if not settled:
                        # A provider failure or a client gone mid-stream: one error row, shielded from the cancel.
                        await asyncio.shield(broke(reason))

            return StreamingResponse(events(), media_type="text/event-stream")
        try:
            done = await provider.complete(alias_row.model_id, body)
        except ProviderError as e:
            return await failed(e)
        await settle(done.input_tokens, done.output_tokens)
        # `tool_calls` is left unset, not None, when there are none: the route drops unset fields, so the key is absent.
        message = (
            ChatMessage(role="assistant", content=done.text, tool_calls=[_tool_call(c) for c in done.tool_calls])
            if done.tool_calls
            else ChatMessage(role="assistant", content=done.text)
        )
        return ChatCompletion(
            id=call_id,
            object="chat.completion",
            created=created,
            model=alias_name,
            choices=[ChatChoice(index=0, message=message, finish_reason=done.finish_reason)],
            usage=ChatUsage(
                prompt_tokens=done.input_tokens,
                completion_tokens=done.output_tokens,
                total_tokens=done.input_tokens + done.output_tokens,
            ),
        )

    # OpenAI's path shape: clients built on the OpenAI SDK append `/chat/completions` to their base URL.
    provider_errors = {
        429: "Over the model key's rate limit or a spend cap (`rate_limited`, ...), or the provider limits the "
        "account's key (`provider_rate_limited`, with the provider's Retry-After)",
        502: "The provider could not be reached (`provider_unreachable`), refused the account's key "
        "(`provider_auth_failed`), refused the request as sent (`provider_bad_request`) or failed (`provider_error`)",
        503: "The provider key the connection names is not saved (`provider_key_missing`)",
        504: "The provider did not answer in time (`provider_timeout`)",
    }
    app.post(
        "/v1/models/chat/completions",
        tags=["completions"],
        response_model=ChatCompletion,
        response_model_exclude_unset=True,
        responses={200: {"content": {"text/event-stream": {}}}, **error_responses(provider_errors)},
    )(completions)

    async def embeddings(
        request: EmbeddingsRequest,
        *,
        presented: Annotated[str, Depends(model_key)],
        x_data_sensitivity: Annotated[str, Header()] = "internal",
        x_run_id: Annotated[str | None, Header()] = None,
        x_step_id: Annotated[str | None, Header()] = None,
        x_tenant_id: Annotated[str | None, Header()] = None,
        x_run_spend_cap: Annotated[str | None, Header()] = None,
    ) -> Embeddings | Response:
        """Vectors for one text or a batch, from an alias of kind embedding, through the same key, budget and clearance
        checks as a completion, and one call-log row per request."""
        inputs = [request.input] if isinstance(request.input, str) else list(request.input)
        # The gate is one transaction, committed (a refusal's row with it) before the provider is called.
        async with isolation.request_transaction():
            gate = await open_gate(
                presented,
                request.model,
                "embedding",
                sensitivity=x_data_sensitivity,
                tenant=x_tenant_id,
                run_cap=x_run_spend_cap,
                run_id=x_run_id,
                step_id=x_step_id,
            )
            if isinstance(gate, Gate) and (not inputs or len(inputs) > MAX_EMBED_INPUTS):
                gate = await gate.refuse(
                    400, "invalid_input", f"Send 1 to {MAX_EMBED_INPUTS} texts to embed, not {len(inputs)}."
                )
        if isinstance(gate, JSONResponse):
            return gate
        try:
            done = await gate.provider.embed(gate.serving.model_id, inputs, request.dimensions)
        except ProviderError as e:
            return await gate.failed(e)
        await gate.settle(done.input_tokens, 0)
        return Embeddings(
            object="list",
            model=request.model,
            data=[EmbeddingRow(object="embedding", index=i, embedding=v) for i, v in enumerate(done.vectors)],
            usage=EmbeddingsUsage(prompt_tokens=done.input_tokens, total_tokens=done.input_tokens),
        )

    app.post(
        "/v1/models/embeddings",
        tags=["completions"],
        response_model=Embeddings,
        responses=error_responses(provider_errors),
    )(embeddings)

    return app


def _version_fields(body: AliasVersionIn, price: tuple[Decimal, Decimal]) -> AliasFields:
    return {
        "provider_id": body.provider_id,
        "model_id": body.model_id,
        "cleared_sensitivity": body.cleared_sensitivity,
        "input_per_million": price[0],
        "output_per_million": price[1],
        "reasoning_effort": body.reasoning_effort,
        "images": body.images,
    }


# The content part types that carry only text. Every other part (an image, a file, audio, or a kind no provider has
# named yet) counts as carrying the page, so a new part type is refused by an alias not cleared rather than let through.
TEXT_PARTS = frozenset({"text", "input_text", "output_text", "refusal"})


def images_in(messages: list[Json]) -> int:
    """How many parts of the request's messages carry something other than text; a string content carries none."""
    count = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            for part in content:
                kind = json_object(part).get("type") if isinstance(part, dict) else None
                count += kind not in TEXT_PARTS
    return count
