"""What a request handler needs, built once in the app lifespan and read from app state."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agent_kernel.ports import KernelPorts
from ops_agents.activities.catalog import Catalog
from ops_agents.activities.gateway import GatewayClient
from ops_agents.graphs.common import GraphDeps
from ops_agents.graphs.definition import CompiledCache
from ops_service_kit.settings import Settings

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
    db: AsyncEngine
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
    # The aliases an agent may name (models-service's when configured); set in the lifespan.
    model_aliases: ModelAliases | None = None


def runtime(request: Request) -> Runtime:
    rt: Runtime = request.app.state.runtime
    return rt
