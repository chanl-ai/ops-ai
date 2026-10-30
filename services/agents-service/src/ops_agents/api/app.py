"""App factory: `create_app(settings)` builds the Runtime API with its engine, catalogue and kernel ports."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import httpx2
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic_ai.models import Model

from ops_agent_kernel.models import ModelsServiceModels, NoModelKeyError, build_model
from ops_agent_kernel.ports import KernelPorts
from ops_agents.activities.catalog import load_catalog
from ops_agents.activities.gateway import GatewayClient, GatewayReplySender, GatewayToolExecutor
from ops_agents.activities.knowledge import KbService, Knowledge, NoKnowledgeService
from ops_agents.activities.tool_directory import CatalogTools, ToolDirectory, ToolsOperations
from ops_agents.activities.tools import LocalReplySender, LocalToolExecutor, ReplySender
from ops_agents.graphs import agent_wrapper
from ops_agents.graphs.checkpointer import open_checkpointer
from ops_agents.graphs.common import GraphDeps
from ops_agents.graphs.definition import CompiledCache, WorkflowDefinition
from ops_agents.graphs.metering import MeteredModels
from ops_agents.graphs.models import GraphModels, PydanticAiModels
from ops_agents.graphs.registry import build_graphs
from ops_files_client import FilesClient
from ops_identity import Auth, ServiceClient, install_auth
from ops_metering import PriceTable
from ops_service_kit.http import operation_id
from ops_service_kit.ids import now_iso
from ops_service_kit.logging import get_logger
from ops_service_kit.settings import Settings
from ops_store import isolation
from ops_store.database import Database, open_database

from ..store.background import BackgroundJobs, heartbeats
from ..store.channels import ChannelStore, Deployment
from ..store.graphs import GraphStore
from ..store.leases import Leases
from ..store.mailboxes import MailboxRow, MailboxStore
from ..store.tenancy import LOCAL_TENANT, SEED, current_team, current_tenant
from ..store.usage import UsageLedger
from . import agent_registry, engine_seed, guardrails, skills, workflow_registry
from .acting_for import CallPeople, acting_for_tokens
from .agent_calls import AgentCalls
from .approval_renewal import ApprovalRenewal
from .child_runs import ChildRuns
from .deps import Runtime
from .envelope import install_error_handlers
from .fencing import ToolsFence
from .file_names import FilesServiceNames
from .key_summaries import PlatformKeySummaries
from .memory import MemoryReads
from .memory_retention import PlatformRetention, expire_forever
from .metering import CountingModels
from .model_aliases import HttpModelAliases, StaticModelAliases
from .model_ledger import LedgerModel, LedgerSource
from .ops_tools import OpsReads
from .people_names import PlatformPeopleNames
from .platform_policies import PlatformPolicies
from .review_sla import PlatformReviewSla
from .review_text import OneDirectoryRead
from .routers import (
    activity,
    agents,
    background,
    batches,
    case_records,
    cases,
    channel_list,
    chat,
    events,
    forms,
    graph_list,
    graphs,
    health,
    model_alias_catalog,
    overview,
    publish_requests,
    reviews,
    service_events,
    step_up,
    templates,
    tool_catalog,
    workflows,
)
from .routers import ai_steps as ai_step_routes
from .routers import case_types as case_type_routes
from .routers import channels as channel_routes
from .routers import chat_settings as chat_settings_routes
from .routers import engine as engine_routes
from .routers import guardrails as guardrail_routes
from .routers import knowledge_usage as knowledge_usage_routes
from .routers import mailboxes as mailbox_routes
from .routers import memories as memory_routes
from .routers import routing as routing_routes
from .routers import run_resume as run_resume_routes
from .routers import skills as skill_routes
from .routers import task_types as task_type_routes
from .routers import tasks as task_routes
from .routers import team_usage as team_usage_routes
from .routers import timers as timer_routes
from .routers import widget as embed_routes
from .routers import widgets as widget_routes
from .schemas import ERROR_RESPONSES
from .sweeper import sweep_forever
from .team_names import PlatformTeamNames
from .timers import poll_forever

log = get_logger("ops_agents.api")


def instance_owner(port: int) -> str:
    """Names this process as a lease owner; distinct per process even on one host and port after a restart."""
    return f"{socket.gethostname()}:{port}:{os.getpid()}:{secrets.token_hex(3)}"


async def seed_workflows(store: GraphStore, seed_dir: Path) -> dict[str, int]:
    """Publishes the seeded workflow definitions; one already stored under the same digest is left as it is, and a
    changed one becomes the next version. Returns the version each seeded name now has in the seed."""
    path = seed_dir / "workflows.json"
    if not path.exists():
        return {}
    seeded: dict[str, int] = {}
    for raw in json.loads(path.read_text()):
        d = WorkflowDefinition.model_validate(raw)
        seeded[d.name] = await store.publish(d.name, d.model_dump(mode="json"), d.digest(), now_iso())
    return seeded


async def seed_deployments(channels: ChannelStore, path: Path | None) -> None:
    """Dev seed: the channel deployments in `path` (seed/deployments.json), upserted so the file is what runs. The graph
    is not checked here: a deployment can name a definition that is published later, and a poll reports the gap."""
    if path is None:
        return
    rows: list[dict[str, Any]] = json.loads(path.read_text())
    for row in rows:
        await channels.put_deployment(
            Deployment(
                row["id"],
                row["graph"],
                row["channel"],
                bool(row.get("paused", False)),
                row.get("multitask", "enqueue"),
                row.get("budget"),
                # The seed's records belong to the seed team, as its agents and workflows do.
                row.get("teamId", agent_registry.SEED_TEAM),
            ),
            now_iso(),
        )


async def seed_mailboxes(db: Database, path: Path | None) -> None:
    """Dev seed: the team mailboxes in `path` (seed/mailboxes.json), in the local tenant, replaced so the file is what
    is connected. A password is a Secrets-page secret by name; the seed sets no secret."""
    if path is None:
        return
    rows: list[dict[str, Any]] = json.loads(path.read_text())
    now = now_iso()
    with isolation.tenant_wide(SEED, tenant_id=LOCAL_TENANT):
        await MailboxStore(db).drop_seeded_except([str(r["id"]) for r in rows])
        for r in rows:
            await MailboxStore(db).put_seed(
                MailboxRow(
                    id=r["id"],
                    team_id=r.get("teamId", agent_registry.SEED_TEAM),
                    name=r["name"],
                    address=r["address"],
                    provider=r["provider"],
                    imap_host=r.get("imapHost"),
                    imap_port=r.get("imapPort"),
                    imap_tls=bool(r.get("imapTls", True)),
                    username=r.get("username"),
                    password_secret=r.get("passwordSecret"),
                    folder=r.get("folder", "inbox"),
                    sender=r.get("sender", "none"),
                    from_address=r.get("fromAddress"),
                    smtp_host=r.get("smtpHost"),
                    smtp_port=r.get("smtpPort"),
                    smtp_starttls=bool(r.get("smtpStarttls", True)),
                    sender_secret=r.get("senderSecret"),
                    created_by="seed",
                    created_at=now,
                    updated_at=now,
                )
            )


# The `area:action` scopes this service claims on another service's public routes (c-168), by audience. Those calls
# also name the team of the request or run, which the receiving service reads instead of any query parameter.
PUBLIC_SCOPES: dict[str, list[str]] = {
    "kb": ["knowledge:view"],
    "tools": ["tools:view"],
    "platform": ["settings:view"],
}


def required_client(
    settings: Settings, http: httpx.AsyncClient, audience: str, *, timeout: float = 10.0
) -> ServiceClient:
    """Another service through ServiceClient, for the tenant (and, on a public route, the team) of the request or run
    it acts for. Raises without a service signing key outside dev: tools and knowledge have no safe fallback."""
    scopes = PUBLIC_SCOPES.get(audience)
    return ServiceClient.for_settings(
        settings,
        http,
        service="agents",
        audience=audience,
        scopes=scopes,
        tenant=current_tenant,
        team=current_team if scopes is not None else _no_team,
        timeout=timeout,
    )


def service_client(settings: Settings, http: httpx.AsyncClient, audience: str) -> ServiceClient | None:
    """`required_client`, or None when this process has no service signing key, so it still starts and each caller
    falls back as it documents."""
    try:
        return required_client(settings, http, audience)
    except ValueError as e:
        log.warning("no service signing key; calls to another service fall back", extra={"error": str(e)})
        return None


def _no_team() -> str | None:
    return None


def create_app(
    settings: Settings,
    *,
    model: Model | None = None,
    engine: Database | None = None,
    checkpointer: Any = None,
    graph_models: GraphModels | None = None,
    gateway: httpx.AsyncClient | None = None,
    models_client: httpx.AsyncClient | None = None,
    completions_client: httpx2.AsyncClient | None = None,
    auth: Auth | None = None,
    kb_client: httpx.AsyncClient | None = None,
    knowledge: Knowledge | None = None,
) -> FastAPI:
    """Tests inject a scripted model, an in-memory database, an in-memory checkpointer and fake graph models;
    `completions_client` reaches an in-process models-service; `auth` resolves callers against a stand-in for
    platform-service; `kb_client` reaches a stand-in for kb-service; `knowledge` replaces kb-service outright (tests
    with fixture passages)."""
    catalog = load_catalog(settings.seed_dir, settings.agents_seed_file)
    db = engine or open_database(settings.database_url)
    model_error: str | None = None
    # With models-service and its key, turns run there on their agent's alias and no provider key is read here.
    through_models: ModelsServiceModels | None = None
    if model is None and settings.models_url and settings.models_key is not None:
        through_models = ModelsServiceModels(
            settings.models_url, settings.models_key.get_secret_value(), http_client=completions_client
        )
        model = through_models.model_for(settings.model_alias)
    if model is None:
        try:
            model = build_model(settings)
        except NoModelKeyError as e:
            model_error = str(e)
    # With a gateway, write tools and send_reply leave this process and run only when OPA accepts their token.
    gateway_http = gateway or (
        httpx.AsyncClient(base_url=settings.gateway_url, timeout=30) if settings.gateway_url else None
    )
    gateway_client = (
        GatewayClient(required_client(settings, gateway_http, "tools", timeout=30)) if gateway_http else None
    )
    # With a gateway, the tools agents may hold and the grants a run hands the model come from tools-service.
    directory: ToolDirectory = (
        ToolsOperations(required_client(settings, gateway_http, "tools", timeout=30))
        if gateway_http
        else CatalogTools(catalog)
    )
    tools = GatewayToolExecutor(gateway_client, directory) if gateway_client else LocalToolExecutor(catalog)
    replies: ReplySender = GatewayReplySender(gateway_client) if gateway_client else LocalReplySender()
    # Every model call of a graph run is one record: the budget sums them, a crashed node's re-run replays them
    # (store/model_calls.py, api/model_ledger.py).
    usage = UsageLedger(db, PriceTable.parse(settings.prices))
    kernel_model = LedgerModel(model, usage, settings.model_alias) if model is not None else None
    per_alias = LedgerSource(through_models, usage) if through_models is not None else None
    kb_http = kb_client or (httpx.AsyncClient(base_url=settings.kb_url, timeout=10) if settings.kb_url else None)
    if knowledge is None:
        knowledge = KbService(required_client(settings, kb_http, "kb")) if kb_http is not None else NoKnowledgeService()
    ports = (
        KernelPorts(model=kernel_model, tools=tools, knowledge=knowledge, models=per_alias) if kernel_model else None
    )

    # models-service answers which aliases an agent may name; without it only the runtime's own alias is known.
    models_http = models_client or (
        httpx.AsyncClient(base_url=settings.models_url, timeout=10) if settings.models_url else None
    )
    # The review deadline policy (reviewSlaHours) lives in platform-service; with no platform URL the default holds.
    policies_http = httpx.AsyncClient(base_url=settings.platform_url, timeout=10) if settings.platform_url else None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        rt = Runtime(settings=settings, catalog=catalog, db=db, ports=ports, model_error=model_error)
        rt.platform_keys = app.state.ops_auth.identity.keys
        if policies_http is not None:
            platform = service_client(settings, policies_http, "platform")
            rt.review_sla = PlatformReviewSla(platform)
            rt.policies = PlatformPolicies(platform)
            rt.team_names = PlatformTeamNames(platform)
            rt.people_names = PlatformPeopleNames(platform)
            rt.key_summaries = PlatformKeySummaries(platform)
        rt.gateway = gateway_client is not None
        rt.model_aliases = (
            HttpModelAliases(service_client(settings, models_http, "models"))
            if models_http is not None
            else StaticModelAliases({settings.model_alias})
        )
        rt.tools = gateway_client
        rt.tool_reviews = gateway_client or (
            GatewayClient(
                required_client(
                    settings, httpx.AsyncClient(base_url=settings.tools_url, timeout=30), "tools", timeout=30
                )
            )
            if settings.tools_url
            else None
        )
        rt.tool_directory = directory
        if settings.files_url:
            files = FilesClient.from_settings(settings, service="agents", scopes=["files:view"])
            rt.file_names = FilesServiceNames(files)
            # A test email's attachments are read back and stored as the mailbox listener stores them.
            rt.start_files = FilesClient.from_settings(
                settings, service="agents", scopes=["files:view", "files:create"]
            )
        rt.knowledge_bases = knowledge
        if gateway_client is not None:
            gateway_client.renewer = ApprovalRenewal(rt)
            gateway_client.people = CallPeople.on(acting_for_tokens(settings, gateway_client.http), db)
        # Published versions and the registry are database rows: they load, list and publish with no model key.
        rt.graph_store = GraphStore(db)
        async with AsyncExitStack() as stack:
            if ports is not None and model is not None:
                # LangGraph's checkpoint tables live on the same database as the chat tables.
                saver = checkpointer or await stack.enter_async_context(open_checkpointer(settings.database_url))
                rt.usage = usage
                models = MeteredModels(
                    CountingModels(graph_models or PydanticAiModels(model)), rt.usage, settings.model_alias
                )
                channels = ChannelStore(db)
                rt.channels = channels
                deps = GraphDeps(
                    catalog,
                    ports,
                    models,
                    replies,
                    settings.model_alias,
                    files=channels,
                    meter=rt.usage,
                    workflows=ChildRuns(rt),
                    agents=AgentCalls(rt),
                    memory=MemoryReads(rt),
                    ops=OpsReads(rt),
                    tools=directory,
                )
                rt.graphs = build_graphs(deps, saver)
                rt.saver = saver
                rt.workflows = CompiledCache(deps, saver)
                rt.leases = Leases(
                    db,
                    owner=instance_owner(settings.port),
                    ttl=settings.lease_ttl_seconds,
                    on_takeover=ToolsFence(gateway_client, rt.graph_store) if gateway_client else None,
                )
                rt.agent_graph = lambda agent_id: agent_wrapper.build(deps, saver, agent_id=agent_id)
                rt.graph_deps = deps
                # Listed background processes (c-516): each writes its heartbeat and logs its jobs in the job's team.
                beats, jobs = heartbeats(db), BackgroundJobs(db)
                sweeper = asyncio.create_task(
                    sweep_forever(rt, settings.sweep_interval_seconds, beats=beats, jobs=jobs)
                )
                stack.callback(sweeper.cancel)
                if settings.timer_poll_seconds > 0 and db.dialect.name == "postgresql":
                    poller = asyncio.create_task(poll_forever(rt, settings.timer_poll_seconds, beats=beats, jobs=jobs))
                    stack.callback(poller.cancel)
                if settings.platform_url:
                    # Memory retention (c-206): the workspace policy lives in platform-service.
                    platform_http = httpx.AsyncClient(base_url=settings.platform_url, timeout=10)
                    stack.push_async_callback(platform_http.aclose)
                    # A process without a signing key still starts, and the read keeps memories when it cannot sign.
                    retention = PlatformRetention(service_client(settings, platform_http, "platform"))
                    expiry = asyncio.create_task(expire_forever(rt, retention, beats=beats))
                    stack.callback(expiry.cancel)
            # Without a seed directory (outside dev, unless one is named) nothing is seeded; the registries still load
            # and serve what is published.
            seed_dir = settings.seed_dir
            seeded = await seed_workflows(rt.graph_store, seed_dir) if seed_dir else {}
            # A seed update opens a publish request, and requests are per tenant (c-333 phase A) while the registries
            # are not yet: the seed's requests are the dev seed's tenant's, as engine_seed's records are.
            with isolation.tenant_wide(SEED, tenant_id=LOCAL_TENANT):
                await agent_registry.load(rt, load_catalog(seed_dir, settings.agents_seed_file))
                if seed_dir:
                    await guardrails.load_seed(rt, guardrails.seed_path(seed_dir, settings.agents_seed_file))
                    await skills.load_seed(rt, skills.seed_path(seed_dir, settings.agents_seed_file))
                    await engine_seed.load_seed(rt, engine_seed.seed_path(seed_dir, settings.agents_seed_file))
                await workflow_registry.load(rt, seed_dir)
                await workflow_registry.follow_seed(rt, seeded)
            if rt.channels is not None:
                await seed_deployments(rt.channels, settings.deployments_seed_file)
            await seed_mailboxes(db, settings.mailboxes_seed_file)
            app.state.runtime = rt
            log.info(
                "runtime_started", agents=len(catalog.agents), graphs=len(rt.graphs), model="ok" if ports else "missing"
            )
            yield
        if gateway_http is not None and gateway is None:
            await gateway_http.aclose()
        if models_http is not None and models_client is None:
            await models_http.aclose()
        if policies_http is not None:
            await policies_http.aclose()
        if through_models is not None and completions_client is None:
            await through_models.client.close()
        await db.dispose()

    app = FastAPI(
        title="Ops AI Runtime",
        version="0.1.0",
        lifespan=lifespan,
        openapi_url="/v1/openapi.json",
        generate_unique_id_function=operation_id,
    )
    install_auth(app, auth or Auth.from_settings(settings, audience="agents"))
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Accept", "Authorization", "X-API-Key", "X-Team-Id"],
    )
    # Outside the console's CORS: the widget routes answer for each deployment's own origins (c-117).
    app.add_middleware(embed_routes.WidgetCors)
    # One tool directory read per request, however many calls its page words (c-508).
    app.add_middleware(OneDirectoryRead)
    install_error_handlers(app)

    def mount(router: APIRouter, tag: str, **kw: Any) -> None:
        # One tag per family in docs/architecture/api.md; every route declares the error envelope.
        app.include_router(router, tags=[tag], responses=ERROR_RESPONSES, **kw)

    mount(health.router, "Health")
    # The console calls `/chat/*` on its base URL; `/v1/chat/*` is the versioned path spec 17 mounts. Both stay out of
    # the OpenAPI document: the chat facade is being removed in favour of the thread calls.
    mount(chat.router, "Chat", include_in_schema=False)
    mount(chat.router, "Chat", prefix="/v1", include_in_schema=False)
    mount(chat_settings_routes.router, "Chat", include_in_schema=False)
    # The widget API reuses the chat facade, so it stays out of the OpenAPI document with it (c-117).
    mount(embed_routes.deployments_router, "Widget", include_in_schema=False)
    mount(embed_routes.mint_router, "Widget", include_in_schema=False)
    mount(embed_routes.config_router, "Widget", include_in_schema=False)
    mount(embed_routes.widget_router, "Widget", include_in_schema=False)
    mount(embed_routes.bundle_router, "Widget", include_in_schema=False)
    mount(graphs.router, "Threads")
    mount(graph_list.router, "Graphs")
    mount(agents.router, "Agents")
    # Before workflows.router: its /v1/workflows/{workflow_id} would take /v1/workflows/node-types as an id.
    mount(engine_routes.router, "Workflows")
    mount(engine_routes.runs_router, "Workflows")
    # An outside system resumes the step it was handed (c-525), by the step's own token; no person's.
    mount(run_resume_routes.router, "Workflows")
    mount(workflows.router, "Workflows")
    mount(workflows.refs_router, "Workflows")
    mount(knowledge_usage_routes.router, "Agents")
    mount(team_usage_routes.router, "Workflows")
    mount(tool_catalog.router, "Agents")
    mount(guardrail_routes.router, "Agents")
    mount(skill_routes.router, "Agents")
    mount(widget_routes.router, "Agents")
    mount(model_alias_catalog.router, "Agents")
    mount(publish_requests.router, "Reviews")
    mount(publish_requests.open_router, "Reviews")
    mount(graphs.versions_router, "Graphs")
    mount(reviews.router, "Threads")
    mount(reviews.console_router, "Reviews")
    mount(cases.router, "Cases")
    mount(case_records.router, "Cases")
    mount(task_type_routes.router, "Reviews")
    mount(case_type_routes.router, "Cases")
    mount(task_routes.router, "Reviews")
    mount(ai_step_routes.router, "Workflows")
    mount(activity.router, "Activity")
    mount(forms.router, "Forms")
    mount(templates.router, "Templates")
    mount(batches.router, "Batches")
    mount(background.router, "Background")
    mount(channel_list.router, "Channels")
    mount(channel_list.live_router, "Channels")
    mount(service_events.router, "Workflows")
    mount(overview.router, "Cases")
    mount(step_up.router, "Auth")
    mount(events.router, "Threads")
    mount(timer_routes.router, "Threads")
    mount(routing_routes.router, "Threads")
    mount(channel_routes.deployments_router, "Deployments")
    mount(memory_routes.router, "Memory")
    mount(mailbox_routes.router, "Channels")
    mount(channel_routes.inbox_router, "Threads")
    return app
