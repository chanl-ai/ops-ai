"""What a request handler needs, built once in the app lifespan and read from app state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request

from ops_agent_kernel.ports import KernelPorts
from ops_agents.activities.catalog import Catalog
from ops_agents.activities.gateway import GatewayClient
from ops_agents.activities.knowledge import KnowledgeBases, NoKnowledgeService
from ops_agents.activities.tool_directory import CatalogTools, ToolDirectory
from ops_agents.graphs.common import GraphDeps
from ops_agents.graphs.definition import CompiledCache
from ops_identity.jwks import JwksCache
from ops_service_kit.settings import Settings
from ops_store.database import Database

from ..store.channels import ChannelStore
from ..store.graphs import GraphStore
from ..store.leases import Leases
from ..store.usage import UsageLedger
from .model_aliases import ModelAliases
from .timer_port import PollingScheduler, TimerScheduler
from .usage import AdmitAll, KeyAdmission


@dataclass
class Runtime:
    settings: Settings
    catalog: Catalog
    # The service's database; health checks it.
    db: Database
    ports: KernelPorts | None
    # Why there is no model, when there is none; turns then fail with this instead of the process refusing to start.
    model_error: str | None = None
    graph_store: GraphStore | None = None
    # Compiled LangGraph graphs by name, built in the lifespan once the checkpointer is open.
    graphs: dict[str, Any] = field(default_factory=dict[str, Any])
    # Definition-built workflows, compiled from a thread's pinned version and cached by digest.
    workflows: CompiledCache | None = None
    leases: Leases | None = None
    # The checkpointer, so a new lease owner can raise the thread's fence before it reads (E2b).
    saver: Any = None
    # Deployments, the channel message ledger, thread inboxes and the files stub (E6).
    channels: ChannelStore | None = None
    # Write tools go through the tool gateway, so an approved resume of a gated call must carry its approval token.
    gateway: bool = False
    # The tools-service client when a gateway is configured; the review service asks it for tool access classes.
    tools: GatewayClient | None = None
    # tools-service for applying tool module review decisions (c-163): the gateway's client, or one for `tools_url`
    # when this service runs without a gateway.
    tool_reviews: GatewayClient | None = None
    # The tools an agent may be granted: tools-service's registry with a gateway, the fixture catalogue without.
    tool_directory: ToolDirectory | None = None
    # The knowledge bases a thread may search: kb-service's when configured, otherwise none (every request 503s).
    knowledge_bases: KnowledgeBases | None = None
    # Told when a timer is armed or cancelled; the poller, the default, reads the timers table instead.
    timer_scheduler: TimerScheduler = field(default_factory=PollingScheduler)
    # Usage rows and thread budgets (E12); set with the graphs.
    usage: UsageLedger | None = None
    # Whether a key may open a new thread; the models service's ledger answers once it exists.
    keys: KeyAdmission = field(default_factory=AdmitAll)
    # Compiles the one-node graph of a published agent; set with the graphs. The registry calls it on publish.
    agent_graph: Callable[[str], Any] | None = None
    # What graph nodes run on; a workflow test run compiles its draft against it.
    graph_deps: GraphDeps | None = None
    # Reads what a chat turn's person said about themselves (c-124); None uses a kernel turn on the runtime's alias.
    memory_extractor: Any = None
    # The aliases an agent may name (models-service's when configured); set in the lifespan.
    model_aliases: ModelAliases | None = None
    # platform-service's public keys as the shared Auth caches them: a platform-issued step-up is verified with the
    # same key that verified the caller's session (api/auth.py). None until the lifespan sets it.
    platform_keys: JwksCache | None = None
    # The tenant's review deadline policy (reviewSlaHours); None counts the default 8 hours.
    review_sla: Any = None
    # Workspace policies read live from platform-service (platform_policies.py); None without a platform URL.
    policies: Any = None
    # Team display names from platform-service (team_names.py); None without a platform URL.
    team_names: Any = None
    # File display names from files-service (file_names.py); None without a files URL.
    file_names: Any = None
    # files-service as a test email's attachments are read and stored (run_starts.py, c-466); None without a files URL.
    start_files: Any = None
    # People's display names from platform-service (people_names.py); None without a platform URL.
    people_names: Any = None
    # API keys from platform-service for the Channels list (key_summaries.py); None without a platform URL.
    key_summaries: Any = None
    # System workflows (service_events.py): the shipped list when None; a test sets its own. Published to a tenant the
    # first time it needs them, once per process and version.
    # The event workflows to provision (seed/event_workflows.json when None), and the (tenant, id) pairs provisioned.
    event_workflows: list[dict[str, Any]] | None = None
    event_workflows_seen: set[tuple[str, str]] = field(default_factory=set[tuple[str, str]])

    def directory(self) -> ToolDirectory:
        return self.tool_directory or CatalogTools(self.catalog)

    def kbs(self) -> KnowledgeBases:
        return self.knowledge_bases or NoKnowledgeService()


def runtime(request: Request) -> Runtime:
    rt: Runtime = request.app.state.runtime
    return rt
