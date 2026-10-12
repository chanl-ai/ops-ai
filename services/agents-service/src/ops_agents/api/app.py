"""App factory: `create_app(settings)` builds the Runtime API with its engine, catalogue and kernel ports."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
from collections.abc import AsyncGenerator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import httpx2
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from pydantic_ai.models import Model
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agent_kernel.models import ModelsServiceModels, NoModelKeyError, build_model
from ops_agent_kernel.ports import KernelPorts
from ops_agents.activities.catalog import load_catalog
from ops_agents.activities.gateway import GatewayClient, GatewayReplySender, GatewayToolExecutor
from ops_agents.activities.knowledge import KeywordPassageStore
from ops_agents.activities.tools import LocalReplySender, LocalToolExecutor, ReplySender
from ops_agents.graphs import agent_wrapper
from ops_agents.graphs.checkpointer import open_checkpointer
from ops_agents.graphs.common import GraphDeps
from ops_agents.graphs.definition import CompiledCache, WorkflowDefinition
from ops_agents.graphs.metering import MeteredModels
from ops_agents.graphs.models import GraphModels, PydanticAiModels
from ops_agents.graphs.registry import build_graphs
from ops_identity import Auth, install_auth, mint_service_token, service_signer
from ops_metering import PriceTable
from ops_service_kit.ids import now_iso
from ops_service_kit.logging import get_logger
from ops_service_kit.settings import Settings

from ..store.channels import ChannelStore
from ..store.graphs import GraphStore
from ..store.leases import Leases
from ..store.tenancy import current_tenant
from ..store.usage import UsageLedger
from . import agent_registry, workflow_registry
from .approval_renewal import ApprovalRenewal
from .child_runs import ChildRuns
from .deps import Runtime
from .envelope import install_error_handlers
from .fencing import ToolsFence
from .metering import CountingModels
from .model_aliases import HttpModelAliases, StaticModelAliases
from .model_ledger import LedgerModel, LedgerSource
from .routers import (
    agents,
    cases,
    chat,
    events,
    graph_list,
    graphs,
    health,
    model_alias_catalog,
    publish_requests,
    reviews,
    step_up,
    tool_catalog,
    workflows,
)
from .routers import channels as channel_routes
from .routers import routing as routing_routes
from .routers import timers as timer_routes
from .schemas import ERROR_RESPONSES
from .sweeper import sweep_forever
from .timers import poll_forever

log = get_logger("ops_agents.api")


def instance_owner(port: int) -> str:
    """Names this process as a lease owner; distinct per process even on one host and port after a restart."""
    return f"{socket.gethostname()}:{port}:{os.getpid()}:{secrets.token_hex(3)}"


async def seed_workflows(store: GraphStore, seed_dir: Path) -> None:
    """Publishes the seeded workflow definitions; one already stored under the same digest is left as it is."""
    path = seed_dir / "workflows.json"
    if not path.exists():
        return
    for raw in json.loads(path.read_text()):
        d = WorkflowDefinition.model_validate(raw)
        await store.publish(d.name, d.model_dump(mode="json"), d.digest(), now_iso())


def operation_id(route: APIRoute) -> str:
    """`<tag>_<handler>`, e.g. `agents_list_agents`: stable across path changes, and the name a generated SDK uses."""
    return f"{route.tags[0]}_{route.name}".lower().replace(" ", "_") if route.tags else route.name


def service_token_for(settings: Settings, audience: str) -> Callable[[], str]:
    """This service's Ed25519 token for another service's internal routes, minted per call for the tenant of the
    request or run it acts for (store/tenancy.py)."""
    signer = service_signer(settings)
    return lambda: mint_service_token(signer, service="agents", audience=audience, tenant_id=current_tenant())


def create_app(
    settings: Settings,
    *,
    model: Model | None = None,
    engine: AsyncEngine | None = None,
    checkpointer: Any = None,
    graph_models: GraphModels | None = None,
    gateway: httpx.AsyncClient | None = None,
    models_client: httpx.AsyncClient | None = None,
    completions_client: httpx2.AsyncClient | None = None,
    auth: Auth | None = None,
) -> FastAPI:
    """Tests inject a scripted model, an in-memory database, an in-memory checkpointer and fake graph models;
    `completions_client` reaches an in-process models-service; `auth` resolves callers against a stand-in for
    platform-service."""
    catalog = load_catalog(settings.seed_dir)
    db = engine or create_async_engine(settings.database_url, pool_pre_ping=True)
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
    gateway_client = GatewayClient(gateway_http, token=service_token_for(settings, "tools")) if gateway_http else None
    tools = GatewayToolExecutor(catalog, gateway_client) if gateway_client else LocalToolExecutor(catalog)
    replies: ReplySender = GatewayReplySender(gateway_client) if gateway_client else LocalReplySender()
    # Every model call of a graph run is one record: the budget sums them, a crashed node's re-run replays them
    # (store/model_calls.py, api/model_ledger.py).
    usage = UsageLedger(db, PriceTable.parse(settings.prices))
    kernel_model = LedgerModel(model, usage, settings.model_alias) if model is not None else None
    per_alias = LedgerSource(through_models, usage) if through_models is not None else None
    ports = (
        KernelPorts(model=kernel_model, tools=tools, knowledge=KeywordPassageStore(catalog), models=per_alias)
        if kernel_model
        else None
    )

    # models-service answers which aliases an agent may name; without it only the runtime's own alias is known.
    models_http = models_client or (
        httpx.AsyncClient(base_url=settings.models_url, timeout=10) if settings.models_url else None
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        rt = Runtime(settings=settings, catalog=catalog, db=db, ports=ports, model_error=model_error)
        rt.gateway = gateway_client is not None
        rt.model_aliases = (
            HttpModelAliases(models_http, service_token_for(settings, "models"))
            if models_http is not None
            else StaticModelAliases({settings.model_alias})
        )
        rt.tools = gateway_client
        if gateway_client is not None:
            gateway_client.renewer = ApprovalRenewal(rt)
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
                sweeper = asyncio.create_task(sweep_forever(rt, settings.sweep_interval_seconds))
                stack.callback(sweeper.cancel)
                if settings.timer_poll_seconds > 0 and db.dialect.name == "postgresql":
                    poller = asyncio.create_task(poll_forever(rt, settings.timer_poll_seconds))
                    stack.callback(poller.cancel)
            await seed_workflows(rt.graph_store, settings.seed_dir)
            await agent_registry.load(rt, load_catalog(settings.seed_dir))
            await workflow_registry.load(rt, settings.seed_dir)
            app.state.runtime = rt
            log.info(
                "runtime_started", agents=len(catalog.agents), graphs=len(rt.graphs), model="ok" if ports else "missing"
            )
            yield
        if gateway_http is not None and gateway is None:
            await gateway_http.aclose()
        if models_http is not None and models_client is None:
            await models_http.aclose()
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
    install_error_handlers(app)

    def mount(router: APIRouter, tag: str, **kw: Any) -> None:
        # One tag per family in docs/architecture/api.md; every route declares the error envelope.
        app.include_router(router, tags=[tag], responses=ERROR_RESPONSES, **kw)

    mount(health.router, "Health")
    # The console calls `/chat/*` on its base URL; `/v1/chat/*` is the versioned path spec 17 mounts. Both stay out of
    # the OpenAPI document: the chat facade is being removed in favour of the thread calls.
    mount(chat.router, "Chat", include_in_schema=False)
    mount(chat.router, "Chat", prefix="/v1", include_in_schema=False)
    mount(graphs.router, "Threads")
    mount(graph_list.router, "Graphs")
    mount(agents.router, "Agents")
    mount(workflows.router, "Workflows")
    mount(workflows.internal_router, "Workflows")
    mount(tool_catalog.router, "Agents")
    mount(model_alias_catalog.router, "Agents")
    mount(publish_requests.router, "Reviews")
    mount(graphs.versions_router, "Graphs")
    mount(reviews.router, "Threads")
    mount(reviews.console_router, "Reviews")
    mount(cases.router, "Cases")
    mount(step_up.router, "Auth")
    mount(events.router, "Threads")
    mount(timer_routes.router, "Threads")
    mount(timer_routes.internal_router, "Threads")
    mount(routing_routes.router, "Threads")
    mount(channel_routes.deployments_router, "Deployments")
    mount(channel_routes.inbox_router, "Threads")
    return app
