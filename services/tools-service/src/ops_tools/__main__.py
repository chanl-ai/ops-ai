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

from ops_access.platform_events import platform_events_router
from ops_agents.activities.catalog import load_catalog
from ops_documents_client import DocumentsClient
from ops_email import EmailProviders, MailSender
from ops_files_client import FilesClient
from ops_identity import Auth, ServiceClient
from ops_identity.fastapi import DEV_TENANT
from ops_service_kit.credentials import credential_store
from ops_service_kit.logging import configure_logging, get_logger
from ops_service_kit.model_calls import StructuredCalls
from ops_service_kit.settings import Settings, require_keys
from ops_store.database import open_database
from ops_store.schema_version import require_current_schema

from .app import create_gateway_app
from .apps import Apps, apps_router
from .auth import Authenticator, Tokens
from .auth.discovery import Discovery
from .code_runs import CodeExecutor, code_signer
from .connections.connect_links import ConnectLinks
from .connections.keepalive import SignInKeepalive, keep_signed_in
from .connections.routes import accounts_router
from .connections.service import ConnectionService
from .defaults import catch_up_at_start
from .egress import EgressPolicy, NewHosts, OverrideResolver, egress_client, egress_transport
from .egress_routes import egress_router
from .expression_routes import expressions_router
from .file_tools import FileTools
from .graph_mailbox import cursor_key, graph_clients
from .header_keys import move_at_start
from .knowledge_tools import KnowledgeSearch
from .mailboxes import MailboxSenders, mailboxes_router
from .mock_routes import mocks_router
from .modules.directory import Directory
from .modules.policy import CheckBeforeSend, PublishPolicy, RequesterMayDecide, WriteApprovals
from .modules.review_handoff import keep_handing_over
from .modules.reviews import Reviews
from .modules.routes import executions_router, modules_router
from .modules.seed import load
from .modules.service import ModuleService
from .modules.tool_users import AgentsToolUsers
from .modules.workflows import AgentsWorkflows
from .opa import OpaClient
from .platform_events import member_removed_handlers, team_created_handlers
from .plugins.host import PluginHost
from .plugins.routes import plugins_router
from .plugins.templates import ServiceCopies, plugin_templates_router
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
from .store.plugin_bindings import PluginBindings
from .store.review_handoffs import ReviewHandoffs
from .store.secrets import SecretStore
from .store.send_policies import SendPolicies
from .store.team_defaults import TeamDefaults
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
        # connected), and no "Runtime demo tools" module offers the fixture tools to agents.
        asyncio.run(_seed(settings, seed, None))
    engine = open_database(settings.database_url)
    directory = Directory.from_seed(seed, datetime.now(UTC))
    store, calls = ModuleStore(engine), CallLog(engine)

    def client(audience: str, base_url: str, scopes: list[str] | None = None) -> ServiceClient:
        """This service's calls to another; each names the tenant (and team) it acts for."""
        http = httpx.AsyncClient(base_url=base_url, timeout=5)
        return ServiceClient.for_settings(settings, http, service="tools", audience=audience, scopes=scopes, timeout=5)

    # The account's egressNewHosts policy decides an unlisted host (ask Security, builders, any public host, block).
    new_hosts = (
        NewHosts(client("platform", settings.platform_url, ["settings:view"])) if settings.platform_url else None
    )
    policy = EgressPolicy(EgressStore(engine), OverrideResolver(settings.egress_resolve), new_hosts)
    ca = str(settings.egress_ca_file) if settings.egress_ca_file else None
    # Every secret value is put and read through the credential store; rows keep only its reference.
    credentials = credential_store(settings)
    secrets = SecretResolver(SecretStore(engine), credentials)
    # Connections sign calls in; their token requests go out through the same egress client as calls.
    # Ops AI's own OAuth client per plugin comes from the install config; the store hands it to an account on it.
    connection_store = ConnectionStore(engine, settings.plugin_clients)
    tokens = Tokens(connection_store, credentials, egress_client(policy, ca_file=ca), policy)
    # A call acting for someone who has not signed in hands back a link to the console page that asks them.
    links = ConnectLinks(connection_store, settings.console_url) if settings.console_url else None
    authenticator = Authenticator(connection_store, secrets, tokens, links)
    agents_url = settings.agents_url or f"http://127.0.0.1:{settings.port}"

    # The install's plugins (its plugins folder, OPS_PLUGINS_DIR), read once at start: a failed one is logged
    # (plugin_failed) and left out. With none, the plugin routes are not mounted and calls never reach a plugin.
    plugins = PluginHost.when_on(
        settings,
        store,
        PluginBindings(engine),
        connection_store,
        # The lookup after a plugin's sign-in goes out through the egress client, as any call does.
        http=egress_client(policy, ca_file=ca),
        policy=policy,
    )
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
    # A plugin's sign-in, token and test requests reach the hosts it declares without the tenant listing them.
    tokens.plugin_hosts = plugins.connection_hosts if plugins else None
    # The call log names a plugin tool by its manifest title.
    modules.titles = plugins.title_of if plugins else None
    # A plugin tool's page names the team's own account of the app.
    modules.team_connections = plugins.team_connection if plugins else None
    modules.awaits_sign_in = plugins.awaits_sign_in if plugins else None
    # send_reply naming a mailbox: the mailbox is read from agents-service as the call's team, its secret is
    # looked up for that team, and its host is dialled at the allow-listed address.
    # Microsoft 365 mailboxes: Graph and its token endpoint, dialled through each tenant's allow-list.
    graph = graph_clients(egress_transport(policy, ca_file=ca), settings.graph_url)
    mailbox_senders = MailboxSenders(
        settings,
        client("agents", agents_url, ["deployments:view"]),
        resolver=secrets,
        egress=policy,
        resend_http=egress_client(policy, ca_file=ca),
        graph=graph,
    )
    connection_service = ConnectionService(
        connection_store,
        secrets,
        credentials,
        tokens,
        directory,
        egress=policy,
        # A sign-in returns to the console's page, which hands the code to this service.
        console_url=settings.console_url,
        security_team=settings.security_team_id,
        # An MCP server's sign-in is found from the server, through the egress client.
        discovery=Discovery(egress_client(policy, ca_file=ca), policy),
        # Test connection signs its read in as a call is, through the same egress client.
        auth=authenticator,
        http=egress_client(policy, ca_file=ca),
        # A plugin's connection takes its instance from the token answer.
        on_token=plugins.on_token if plugins else None,
        plugin_settings=plugins.account_settings if plugins else None,
        # A refused sign-in says what the plugin's sign_in_errors say of its code.
        sign_in_errors=plugins.sign_in_error if plugins else None,
    )
    connection_service.app_display = plugins.display_of if plugins else None
    tool_users = AgentsToolUsers(client("agents", agents_url, ["agents:view"]))
    # An app's Resources tab joins the copies agents-service and documents-service keep, read as the caller's team.
    documents_url = settings.documents_url or f"http://127.0.0.1:{settings.documents_port}"
    resource_copies = ServiceCopies(
        client("agents", agents_url, ["agents:view"]),
        client("documents", documents_url, ["documents:view"]),
        client("kb", settings.kb_url, ["knowledge:view"]) if settings.kb_url else None,
    )
    apps = Apps(connection_service, store, plugins, modules, tool_users)
    app = create_gateway_app(
        opa=OpaClient(httpx.AsyncClient(base_url=settings.opa_url, timeout=5)),
        registry=ToolRegistry(catalog, store, plugins, connection_store),
        plugins=plugins,
        # A tool page's Real run goes through this gateway's checks.
        modules=modules,
        cursor_key=cursor_key(settings.secrets_key.get_secret_value()),
        # /mcp is served only with the mcp_gateway flag on in the install config.
        flags=settings.feature_flags,
        log=calls,
        # The mail provider settings pick (OPS_MAIL_PROVIDER); a missing secret stops start-up here. An SMTP password
        # named by OPS_SMTP_PASSWORD_SECRET is read from the Secrets page at each send, as send_reply.
        runner=LocalToolRunner(
            catalog,
            mail_for=mail_senders(settings, secrets),
            mailbox_sender=mailbox_senders.sender,
            cases=client("agents", agents_url, ["cases:view", "cases:create"]),
            decisions=modules,
            # read_file and read_document read through documents-service as the calling team.
            file_tools=FileTools(
                FilesClient.from_settings(settings, service="tools", scopes=["files:view"]),
                DocumentsClient.from_settings(settings, service="tools", scopes=["documents:view", "documents:run"]),
            ),
            # search_knowledge searches the calling team's knowledge bases through kb-service.
            knowledge=KnowledgeSearch(client("kb", settings.kb_url, ["knowledge:view"])) if settings.kb_url else None,
        ),
        review_key=settings.review_key.get_secret_value(),
        auth=Auth.from_settings(settings, audience="tools"),
        # The team's toolWritesNeedApproval, read from platform-service on each call so a change applies at once.
        write_approvals=WriteApprovals(client("platform", settings.platform_url, ["settings:view"]))
        if settings.platform_url
        else None,
        # Check before sending: the team's checkBeforeSend read live, its sending policy here, and the judge on
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
            # Tool access requests and module reviews start their system workflows through these events.
            lambda: keep_relaying(engine, client("agents", agents_url, ["events:emit"])),
            # Once at start: every team behind this release's defaults version is brought up to date.
            lambda: catch_up_at_start(store, TeamDefaults(engine)),
            # Once at start: a tool's sign-in header saved before they were refused moves to its connection.
            lambda: move_at_start(store, connection_store),
            # Once a day: every sign-in left unused for 20 days is refreshed, so no system ends it for being idle.
            lambda: keep_signed_in(SignInKeepalive(TeamDefaults(engine), connection_store, authenticator)),
        ),
        secret_resolver=secrets,
        authenticator=authenticator,
        directory=directory,
        # Code operations run on runner-service; its calls back are checked with this service's own key.
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
            secrets_router(secrets, modules=store, credentials=connection_store),
            send_policy_router(SendPolicies(engine), directory),
            mocks_router(MockStore(engine), store, directory, security_team=settings.security_team_id),
            *(
                [
                    plugins_router(
                        apps.plugin_accounts,
                        directory,
                        users=tool_users,
                    )
                ]
                if apps.plugin_accounts
                else []
            ),
            *([plugin_templates_router(plugins, resource_copies)] if plugins else []),
            accounts_router(connection_service, directory),
            apps_router(apps, directory),
            platform_events_router(
                {
                    **member_removed_handlers(connection_service.store, credentials),
                    **team_created_handlers(store, TeamDefaults(engine)),
                }
            ),
        ),
    )
    uvicorn.run(app, host=settings.bind_host, port=settings.gateway_port, log_level="info")


if __name__ == "__main__":
    main()
