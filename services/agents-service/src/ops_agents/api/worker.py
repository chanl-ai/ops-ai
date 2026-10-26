"""The workflow runner's worker process: `python -m ops_agents.api.worker` (`make -C services/agents-service worker`).

It claims engine_work rows and runs v2 workflows (ops_engine.worker) with this service's adapters (engine_host.py).
It serves no HTTP and needs no model. The API process keeps its own sweeper and timer poller for v1 threads; v2
runs are recovered here, by claiming a row whose claim lapsed. Settings come from the environment as for the API:
OPS_DATABASE_URL, OPS_GATEWAY_URL, OPS_LEASE_TTL_SECONDS, OPS_ENGINE_POLL_SECONDS, OPS_ENGINE_CONCURRENCY.
"""

from __future__ import annotations

import asyncio
import signal
from contextlib import AbstractContextManager, AsyncExitStack
from pathlib import Path
from typing import Any

import httpx

from ops_agents.activities.gateway import GatewayClient
from ops_agents.graphs.checkpointer import open_checkpointer
from ops_documents_client import DocumentsClient
from ops_email import MailSource
from ops_engine import default_registry
from ops_engine.ports import EnginePorts, Faults
from ops_engine.store import DefinitionStore, RunStore
from ops_engine.worker import Worker, WorkerHost
from ops_files_client import FilesClient
from ops_service_kit.logging import configure_logging, get_logger
from ops_service_kit.settings import Settings, require_keys
from ops_store import background, isolation
from ops_store.isolation import Isolation
from ops_store.schema_version import require_current_schema

from ..store.background import BackgroundJobs, heartbeats
from ..store.cases import CaseStore
from ..store.engine import AsyncEngine, EngineTransactions, connect
from ..store.events import EventLog
from ..store.graphs import GraphStore
from ..store.leases import Leases
from ..store.mailboxes import MailboxRow
from ..store.tenancy import ENGINE_PASS
from .ai_steps_gate import RunTeamRules
from .app import instance_owner, required_client, service_client
from .email_trigger import EmailTriggers
from .engine_agents import kernel_agents
from .engine_cases import RunCases
from .engine_documents import DocumentsExtractions, RunFileData
from .engine_host import (
    ApprovalMinter,
    GatewayExpressions,
    GatewayTools,
    KillAfterNode,
    RunEvents,
    RunReviews,
    ThreadLeases,
    assisted_reviews,
)
from .engine_resume import resume_link
from .engine_runs import WorkflowStarts
from .fencing import ToolsFence
from .mailbox_gateway import mailbox_client, mailbox_source
from .platform_policies import PlatformPolicies
from .review_sla import PlatformReviewSla
from .service_events import reminders
from .task_type_seeds import StoredTaskTypes

# This service's own migration chain: it starts only on a database that records the chain's head.
MIGRATIONS = Path(__file__).resolve().parents[3] / "migrations"

log = get_logger("ops_agents.api.worker")


async def serve(settings: Settings, stop: asyncio.Event) -> None:
    db = connect(settings.database_url)
    async with AsyncExitStack() as stack:
        stack.push_async_callback(db.dispose)
        gateway: GatewayClient | None = None
        http: httpx.AsyncClient | None = None
        if settings.gateway_url:
            http = httpx.AsyncClient(base_url=settings.gateway_url, timeout=30)
            stack.push_async_callback(http.aclose)
            gateway = GatewayClient(required_client(settings, http, "tools", timeout=30))
        kb_http: httpx.AsyncClient | None = None
        if settings.kb_url:
            kb_http = httpx.AsyncClient(base_url=settings.kb_url, timeout=10)
            stack.push_async_callback(kb_http.aclose)
        # Agent steps run kernel turns here; with no model configured they fail with that reason.
        agents = kernel_agents(
            settings,
            db,
            gateway=gateway,
            tools=required_client(settings, http, "tools", timeout=30) if http is not None else None,
            kb=required_client(settings, kb_http, "kb") if kb_http is not None else None,
        )
        saver = await stack.enter_async_context(open_checkpointer(settings.database_url))
        owner = f"worker:{instance_owner(settings.port)}"
        leases = Leases(
            db,
            owner=owner,
            ttl=settings.lease_ttl_seconds,
            # A takeover raises tools-service's fence first, as the v1 sweeper's does (E2c).
            on_takeover=ToolsFence(gateway, GraphStore(db)) if gateway else None,
        )
        minter = ApprovalMinter(db, settings.review_key.get_secret_value(), settings.review_token_ttl_seconds)
        # One kernel for agent steps and AI steps (c-298): an AI step's call is the agent port's prompt.
        ports = EnginePorts(tools=GatewayTools(gateway, minter), reviews=RunReviews(), agents=agents, prompts=agents)
        # Start workflow steps: children in the parent run's team and mode, under the pass's tenant.
        ports.runs = WorkflowStarts(RunStore(EngineTransactions(db)), DefinitionStore(EngineTransactions(db)))
        # Open case and Add to case steps: the run's team's cases (c-219).
        ports.cases = RunCases(RunStore(EngineTransactions(db)), CaseStore(db))
        # Review steps that name a task type pin its published version as they pause (c-288).
        ports.task_types = StoredTaskTypes(db)
        if gateway is not None:
            ports.expressions = GatewayExpressions(gateway)
        if settings.documents_url:
            # Extract from file asks documents-service's extraction API as the run's team (c-256).
            # Purge steps remove what was read from a deleted file (c-250).
            documents = DocumentsClient.from_settings(
                settings, service="agents", scopes=["documents:view", "documents:run", "documents:delete"]
            )
            stack.push_async_callback(documents.aclose)
            ports.documents = DocumentsExtractions(documents, EngineTransactions(db))
            # Extract from text reads a document type's fields from the same service (c-298).
            ports.document_types = ports.documents
        if settings.files_url:
            # Save data on file steps record what was read on the file, as the run's team (c-250).
            file_data = FilesClient.from_settings(settings, service="agents", scopes=["files:edit"])
            stack.push_async_callback(file_data.aclose)
            ports.file_data = RunFileData(file_data, EngineTransactions(db))
        ports.faults = Faults(ignore_recorded=settings.engine_fault_ignore_recorded)
        if settings.engine_fault_kill_after_node:
            ports.hooks = KillAfterNode(settings.engine_fault_kill_after_node)
        # The workspace's review deadline, for a review step that expires and sets none (reviewSlaHours).
        review_sla = None
        if settings.platform_url:
            platform_http = await stack.enter_async_context(
                httpx.AsyncClient(base_url=settings.platform_url, timeout=10)
            )
            review_sla = PlatformReviewSla(service_client(settings, platform_http, "platform"))
            if agents is not None:
                # Task assist (c-302) writes a typed task's help as its step pauses, where the team turned it on.
                policies = PlatformPolicies(service_client(settings, platform_http, "platform"))
                ports.reviews = assisted_reviews(stack, db, agents, policies)
                # AI steps run only where the run's team allows them, masked unless it turned that off (c-298, c-321).
                agents.rules = RunTeamRules(db, policies)
        host = WorkerHost(
            tx=EngineTransactions(db),
            registry=default_registry(),
            ports=ports,
            leases=ThreadLeases(leases),
            events=RunEvents(EventLog(db)),
            checkpointer=saver,
            run_scope=engine_pass,
            owner=owner,
            concurrency=settings.engine_concurrency,
            enter_run=enter_run,
            review_hours=review_sla.hours if review_sla is not None else None,
            remind=reminders(db),
            resume_link=lambda run, waiting, seconds: resume_link(
                settings.review_key.get_secret_value(),
                tenant=str(run["tenant_id"]),
                team=str(run["team_id"]),
                run_id=str(run["id"]),
                waiting=waiting,
                seconds=seconds,
            ),
        )
        listener = email_listener(settings, db, owner, stack)
        if listener is not None:
            listening = asyncio.create_task(keep_mail_listening(listener, stop, settings.email_poll_seconds))
            stack.push_async_callback(lambda: asyncio.wait_for(listening, None))
        log.info(
            "engine_worker_started",
            owner=owner,
            gateway=bool(gateway),
            agents=agents is not None,
            poll=settings.engine_poll_seconds,
        )
        # The workflow worker is a listed background process (c-516): its heartbeat is written from this loop.
        await Worker(host, background.Beat("workflow_worker", heartbeats(db))).run_forever(
            stop, settings.engine_poll_seconds
        )
    log.info("engine_worker_stopped", owner=owner)


def engine_pass(tenant_id: str) -> AbstractContextManager[Isolation]:
    """A claimed run's pass, in the tenant its row names, for every team until `enter_run` names the run's."""
    return isolation.tenant_wide(ENGINE_PASS, tenant_id=tenant_id)


def enter_run(run: dict[str, Any]) -> None:
    """The run's team for its pass, so a tool call's service token names it as a person's request would. Each pass is
    its own task, so the team set here is that run's alone; a run with no team stays tenant-wide."""
    if team := run.get("team_id"):
        isolation.enter(isolation.tenant(), str(team), kind="worker")


async def keep_mail_listening(listener: EmailTriggers, stop: asyncio.Event, every_s: float) -> None:
    """Restarts the mail listener after a crash, through the same runner as the other loops (c-516)."""

    async def once() -> int:
        await listener.run_forever(stop, every_s)
        return 0

    store = listener.beat.store if listener.beat is not None else background.LOCAL
    await background.run("mail_listener", once, stop=stop, store=store, every_s=every_s)


def email_listener(settings: Settings, db: AsyncEngine, owner: str, stack: AsyncExitStack) -> EmailTriggers | None:
    """The mailbox listener. Mailboxes are records connected on Channels > Email, so it runs whenever their mail can
    be read and stored: with a files-service (attachments go there first) and a tools-service (it reads IMAP with the
    mailbox's secret). Without either it logs why and reads nothing."""
    if not settings.files_url or not settings.gateway_url:
        log.warning("email_listener_off", reason="OPS_FILES_URL and OPS_GATEWAY_URL are both needed to read mailboxes")
        return None
    files = FilesClient.from_settings(settings, service="agents", scopes=["files:view", "files:create"])
    stack.push_async_callback(files.aclose)
    gateway = httpx.AsyncClient(base_url=settings.gateway_url, timeout=60)
    stack.push_async_callback(gateway.aclose)
    mail = mailbox_client(settings, gateway)

    def sources(mailbox: MailboxRow, folder: str) -> MailSource:
        return mailbox_source(settings, mailbox, folder, mail)

    triggers = EmailTriggers(
        db,
        sources,
        files,
        Leases(db, owner=owner, ttl=settings.lease_ttl_seconds),
        idle_seconds=settings.email_idle_seconds,
    )
    triggers.beat, triggers.starts.jobs = background.Beat("mail_listener", heartbeats(db)), BackgroundJobs(db)
    return triggers


def main() -> None:
    configure_logging()
    settings = Settings()
    require_keys(settings, "review_key")
    require_current_schema(settings.database_url, MIGRATIONS)

    async def run() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        await serve(settings, stop)

    asyncio.run(run())


if __name__ == "__main__":
    main()
