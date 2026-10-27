"""`uv run python -m ops_tools`: the tool gateway on settings.gateway_port (8720), deciding with OPA at opa_url, with
the tool-module registry at /v1/tool-modules. In dev the registry is seeded with the console's modules."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import uvicorn

from ops_agents.activities.catalog import load_catalog
from ops_email import EmailProviders, MailSender
from ops_identity import Auth, ServiceClient
from ops_identity.fastapi import DEV_TENANT
from ops_policy import AesGcmCipher
from ops_service_kit.logging import configure_logging, get_logger
from ops_service_kit.model_calls import StructuredCalls
from ops_service_kit.settings import Settings, require_keys
from ops_store.database import open_database
from ops_store.schema_version import require_current_schema

from .app import create_gateway_app
from .auth import Authenticator, Tokens
from .auth.discovery import Discovery
from .code_runs import CodeExecutor, code_signer
from .connections.routes import connections_router
from .connections.service import ConnectionService
from .egress import EgressPolicy, OverrideResolver, egress_client, egress_transport
from .egress_routes import egress_router
from .expression_routes import expressions_router
from .graph_mailbox import graph_clients
from .mailboxes import MailboxSenders, mailboxes_router
from .mock_routes import mocks_router
from .modules.directory import Directory
from .modules.policy import CheckBeforeSend, PublishPolicy, RequesterMayDecide, WriteApprovals
from .modules.review_handoff import keep_handing_over
from .modules.reviews import Reviews
from .modules.routes import executions_router, modules_router
from .modules.seed import load
from .modules.service import ModuleService
from .modules.workflows import AgentsWorkflows
from .opa import OpaClient
from .registry import ToolRegistry
from .secrets import SecretResolver
from .secrets.routes import secrets_router
from .send_check import SendCheck
from .send_policy_routes import send_policy_router
from .store import CallLog
from .store.connections import ConnectionStore
from .store.egress import EgressStore
from .store.event_relay import keep_relaying
from .store.mocks import MockStore
from .store.modules import ModuleStore
from .store.review_handoffs import ReviewHandoffs
from .store.secrets import SecretStore
from .store.send_policies import SendPolicies
from .tools import LocalToolRunner, ToolCaller

# This service's own migration chain: it starts only on a database that records the chain's head.
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"

log = get_logger("ops_tools")


async def secret_value(secrets: SecretResolver, tenant_id: str, team_id: str | None, name: str) -> str:
    """The platform sender's secret (the SMTP password) in the team the call acts in."""
    return (await secrets.lookup(tenant_id, team_id, [name], tool="send_reply", actor="tools:send_reply"))[name]


def mail_senders(settings: Settings, secrets: SecretResolver) -> Callable[[ToolCaller], MailSender]:
    """One sender per tenant and team, made at its first send and kept: each reads its own team's SMTP password, and
    its provider clients and token are reused rather than opened per message."""
    senders: dict[tuple[str, str | None], MailSender] = {}

    def sender(caller: ToolCaller) -> MailSender:
        tenant, team = caller.tenant_id, caller.team_id
        if (tenant, team) not in senders:
            senders[tenant, team] = EmailProviders.from_settings(
                settings, secret=lambda name: secret_value(secrets, tenant, team, name)
            ).sender()
        return senders[tenant, team]

    return sender


async def _seed(settings: Settings, seed: dict[str, Any], catalog: list[dict[str, Any]] | None) -> None:
    engine = open_database(settings.database_url)
    # The dev seed's modules belong to the tenant dev sign-in acts in.
    added = await load(ModuleStore(engine), seed, tenant_id=DEV_TENANT, now=datetime.now(UTC), catalog=catalog)
    await engine.dispose()
    log.info("tool_modules_seeded", added=added)


def main() -> None:
    settings = Settings()
    require_keys(settings, "review_key", "secrets_key")
    require_current_schema(settings.database_url, MIGRATIONS)
    configure_logging()
    catalog = load_catalog(settings.seed_dir)
    seed = json.loads(settings.tools_seed_file.read_text())
    dev = settings.environment == "dev"
    if dev:
        # Without the agents' fixture catalogue: seeded operations run from their stubs (or their endpoints once
        # connected), and no "Runtime demo tools" module offers the fixture tools to agents (c-048 G1).
        asyncio.run(_seed(settings, seed, None))
    engine = open_database(settings.database_url)
    directory = Directory.from_seed(seed, datetime.now(UTC))
    store, calls = ModuleStore(engine), CallLog(engine)
    policy = EgressPolicy(EgressStore(engine), OverrideResolver(settings.egress_resolve))
    ca = str(settings.egress_ca_file) if settings.egress_ca_file else None
    cipher = AesGcmCipher(settings.secrets_key.get_secret_value())
    secrets = SecretResolver(SecretStore(engine), cipher)
    # Connections sign calls in (c-330); their token requests go out through the same egress client as calls.
    connection_store = ConnectionStore(engine)
    tokens = Tokens(connection_store, cipher, egress_client(policy, ca_file=ca), policy)
    authenticator = Authenticator(connection_store, secrets, tokens)
    agents_url = settings.agents_url or f"http://127.0.0.1:{settings.port}"

    def client(audience: str, base_url: str, scopes: list[str] | None = None) -> ServiceClient:
        """This service's calls to another; each names the tenant (and team) it acts for."""
        http = httpx.AsyncClient(base_url=base_url, timeout=5)
        return ServiceClient.for_settings(settings, http, service="tools", audience=audience, scopes=scopes, timeout=5)

    modules = ModuleService(
        store,
        directory,
        calls,
        egress=policy,
        http=egress_client(policy, ca_file=ca),
        secrets=secrets,
        security_team=settings.security_team_id,
        workflows=AgentsWorkflows(client("agents", agents_url, ["workflows:view"])),
        reviews=Reviews(client("agents", agents_url)),
        # The team's publish-review mode, read from platform-service on each publish so a change applies at once.
        publish_policy=PublishPolicy(client("platform", settings.platform_url, ["settings:view"]))
        if settings.platform_url
        else None,
        requester_policy=RequesterMayDecide(
            client("platform", settings.platform_url, ["settings:view"]) if settings.platform_url else None,
            dev=settings.dev_policies,
        ),
        auth=authenticator,
    )
    # send_reply naming a mailbox (c-200): the mailbox is read from agents-service as the call's team, its secret is
    # looked up for that team, and its host is dialled at the allow-listed address.
    # Microsoft 365 mailboxes (c-228): Graph and its token endpoint, dialled through each tenant's allow-list.
    graph = graph_clients(egress_transport(policy, ca_file=ca), settings.graph_url)
    mailbox_senders = MailboxSenders(
        settings,
        client("agents", agents_url, ["deployments:view"]),
        resolver=secrets,
        egress=policy,
        resend_http=egress_client(policy, ca_file=ca),
        graph=graph,
    )
    app = create_gateway_app(
        opa=OpaClient(httpx.AsyncClient(base_url=settings.opa_url, timeout=5)),
        registry=ToolRegistry(catalog, store),
        log=calls,
        # The mail provider settings pick (OPS_MAIL_PROVIDER); a missing secret stops start-up here. An SMTP password
        # named by OPS_SMTP_PASSWORD_SECRET is read from the Secrets page at each send, as send_reply.
        runner=LocalToolRunner(
            catalog,
            mail_for=mail_senders(settings, secrets),
            mailbox_sender=mailbox_senders.sender,
            cases=client("agents", agents_url, ["cases:view", "cases:create"]),
            decisions=modules,
        ),
        review_key=settings.review_key.get_secret_value(),
        auth=Auth.from_settings(settings, audience="tools"),
        # The team's toolWritesNeedApproval, read from platform-service on each call so a change applies at once.
        write_approvals=WriteApprovals(client("platform", settings.platform_url, ["settings:view"]))
        if settings.platform_url
        else None,
        # Check before sending (c-300): the team's checkBeforeSend read live, its sending policy here, and the judge on
        # this service's own model key; with no models-service, a team with the setting on has every write wait.
        send_check=SendCheck(
            SendPolicies(engine),
            CheckBeforeSend(client("platform", settings.platform_url, ["settings:view"])),
            StructuredCalls(
                httpx.AsyncClient(base_url=settings.models_url, timeout=30), settings.models_key.get_secret_value()
            )
            if settings.models_url and settings.models_key
            else None,
        )
        if settings.platform_url
        else None,
        egress=policy,
        http_client=egress_client(policy, ca_file=ca),
        cors_origins=tuple(settings.cors_origins),
        background=(
            lambda: keep_handing_over(ReviewHandoffs(engine), client("agents", agents_url, ["tools:publish"])),
            # Tool access requests and module reviews start their system workflows through these events (c-257).
            lambda: keep_relaying(engine, client("agents", agents_url, ["events:emit"])),
        ),
        secret_resolver=secrets,
        authenticator=authenticator,
        directory=directory,
        # Code operations run on runner-service (c-531); its calls back are checked with this service's own key.
        code=CodeExecutor(
            ServiceClient.for_settings(
                settings,
                httpx.AsyncClient(base_url=settings.runner_url, timeout=90),
                service="tools",
                audience="runner",
                timeout=90,
            )
            if settings.runner_url
            else None,
            code_signer(settings.secrets_key.get_secret_value()),
        ),
        routers=(
            modules_router(modules, directory),
            executions_router(modules, directory),
            mailboxes_router(settings, secrets, policy, graph),
            egress_router(EgressStore(engine)),
            expressions_router(),
            secrets_router(SecretStore(engine), cipher, modules=store),
            send_policy_router(SendPolicies(engine), directory),
            mocks_router(MockStore(engine), store, directory, security_team=settings.security_team_id),
            connections_router(
                ConnectionService(
                    connection_store,
                    SecretStore(engine),
                    cipher,
                    tokens,
                    directory,
                    egress=policy,
                    # A sign-in returns to the console's page, which hands the code to this service.
                    console_url=settings.console_url,
                    security_team=settings.security_team_id,
                    # An MCP server's sign-in is found from the server, through the egress client (c-331).
                    discovery=Discovery(egress_client(policy, ca_file=ca), policy),
                ),
                directory,
            ),
        ),
    )
    uvicorn.run(app, host=settings.bind_host, port=settings.gateway_port, log_level="info")


if __name__ == "__main__":
    main()
