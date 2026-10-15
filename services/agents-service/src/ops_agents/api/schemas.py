"""Response models for the OpenAPI document: the envelope, the error, list pages, and the console contract types the
registry routes return (apps/console/src/lib/types/domain.ts).

Routes build their JSON by hand and return it through `ok()`, so FastAPI documents these models without validating
against them. The API tests close that gap: every response they receive is validated against its route's declared
model (tests/contract.py), and the models refuse unknown fields, so a field added to a route and not to its model
fails a test.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict, Field
from pydantic.alias_generators import to_camel

# The envelope models live in ops_service_kit.http; the routers keep importing them from here.
from ops_service_kit.http import (
    Envelope,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    ErrorBody,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    ErrorEnvelope,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    ListResult,
    Out,
    Pagination,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    error_responses,
)

ERROR_RESPONSES = error_responses({503: "Degraded: no model, or the graph runtime did not start"})


# ── agents ──


class Guardrails(Out):
    redact_pii: bool
    max_tool_calls_per_turn: int
    when_unsure: Literal["handoff", "ask", "decline"]
    blocked_topics: list[str]


class UsedIn(Out):
    workflow_id: str
    workflow_name: str
    pinned_version: int
    status: Literal["live", "draft", "paused"]


class Agent(Out):
    id: str
    name: str
    slug: str
    role: str
    instructions: str
    model: str
    channels: list[str]
    tool_ids: list[str]
    # Granted ids the tool directory no longer offers; the next save drops them.
    stale_tool_ids: list[str]
    collections: list[str]
    owner: str
    paused: bool
    availability: Literal["published", "not_published", "paused"]
    version: int
    published_version: int | None
    updated_at: str
    tasks24h: int = Field(alias="tasks24h")
    auto_resolved_rate: float
    workflow_ids: list[str]
    guardrails: Guardrails
    wrapper_workflow_id: str | None = None
    used_in: list[UsedIn]


class AgentVersion(Out):
    version: int
    note: str
    changes: list[str]
    current: bool
    state: Literal["draft", "in_review", "published", "superseded", "rejected"]
    saved_at: str
    saved_by: str
    published_at: str | None = None
    published_by: str | None = None
    review_id: str | None = None


class ToolCallView(Out):
    name: str
    input: str
    output: str


class CitationView(Out):
    source: str
    section: str


class WouldPause(Out):
    gate: str
    reviewers: str


class AgentTestTurn(Out):
    reply: str
    tool_calls: list[ToolCallView]
    citations: list[CitationView]
    took_ms: int
    # The model alias the turn ran on: the agent's, or the runtime's when the agent names none.
    model: str
    would_pause: WouldPause | None = None


class Tool(Out):
    """A published tools-service operation an agent may be granted; `server` is its module's name."""

    id: str
    name: str
    server: str
    module_id: str | None
    description: str
    access: Literal["read", "write"]
    input_schema: dict[str, Any]
    requires_approval: bool
    approval: str | None


class ModelAlias(Out):
    """A chat alias an agent may name. Clearance and prices come from models-service; without it the runtime's own
    alias is listed by name alone."""

    name: str
    kind: Literal["chat"]
    cleared_sensitivity: str | None = None
    input_per_million: str | None = None
    output_per_million: str | None = None


# ── reviews of publish requests ──


class ReviewPolicy(Out):
    id: str
    name: str
    condition: str
    reviewers: str
    sla: str
    on_timeout: str
    four_eyes: bool


class AgentPublishRequest(Out):
    agent_id: str
    agent_name: str
    version: int
    from_version: int | None
    note: str
    requested_by: str
    saved_by: str
    tier: Literal["critical", "high", "medium", "low"]
    tier_reason: str
    approvals_needed: Literal[1, 2]
    candidate: Any = None
    published: Any = None
    failing: int
    blockers: list[str]
    changes: list[str]


class ValidationSummary(Out):
    passed: int
    total: int
    regressions: int
    checks_failing: int


class PublishRequestInfo(Out):
    workflow_id: str
    from_version: int
    to_version: int
    note: str
    requested_by: str
    changes: list[str]
    validation: ValidationSummary | None
    digest: str


class PublishReview(Out):
    """The console's `Review` as a publish request carries it: `agent_publish` or `publish_request`."""

    id: str
    title: str
    customer: str
    workflow_id: str
    workflow_name: str
    agent_slug: str
    agent_name: str | None
    kind: Literal["agent_publish", "publish_request"]
    risk: Literal["critical", "high", "medium", "low"]
    confidence: float
    proposal: str
    action_tool: str
    currency: str
    policy: ReviewPolicy
    sla_minutes: int
    approvals: list[str]
    status: Literal["pending", "in_review", "approved", "rejected", "returned"]
    created_at: str
    decided_at: str | None = None
    decision_reason: str | None = None
    reasoning: list[str]
    evidence: list[Any]
    agent_publish: AgentPublishRequest | None = None
    publish: PublishRequestInfo | None = None


# ── workflows ──


class RouteField(Out):
    name: str
    type: Literal["text", "number", "boolean"]


class RouteOp(Out):
    op: str
    label: str
    types: list[Literal["text", "number", "boolean"]]
    # The value is a list of candidates (`in`).
    takes_list: bool = Field(default=False, alias="list")


class RouteVocabulary(Out):
    fields: list[RouteField]
    ops: list[RouteOp]


class GraphNode(Out):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="allow")

    id: str
    type: str
    data: dict[str, Any]
    position: dict[str, float] | None = None


class GraphEdge(Out):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="allow")

    id: str
    source: str
    target: str
    source_handle: str | None = None


class WorkflowGraph(Out):
    workflow_id: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class PendingPublish(Out):
    review_id: str
    to_version: int
    requested_by: str


class WorkflowRef(Out):
    """What another service needs about a workflow: its id, name, owner group and owning team (internal route)."""

    id: str
    name: str
    owner: str
    team_id: str
    status: str


class Workflow(Out):
    id: str
    name: str
    description: str
    owner: str
    trigger: str
    agent_slugs: list[str]
    step_count: int
    gate_count: int
    runs24h: int = Field(alias="runs24h")
    reviewed24h: int = Field(alias="reviewed24h")
    open_reviews: int
    status: Literal["live", "draft", "paused"]
    version: int
    updated_at: str
    pending_publish: PendingPublish | None = None
    deployment_count: int
    kind: Literal["standard", "email_intake"]


class WorkflowDraft(Out):
    graph: WorkflowGraph
    saved_at: str
    saved_by: str


class WorkflowDetail(Workflow):
    graph: WorkflowGraph
    draft: WorkflowDraft | None = None


class TestOutcome(Out):
    passed: bool
    paused: bool
    tools_called: list[str]
    reply: str
    failure: str | None = None


class TestResult(Out):
    case_id: str
    case_name: str
    draft: TestOutcome
    live: TestOutcome | None
    regression: bool


class ValidationRun(Out):
    id: str
    workflow_id: str
    ran_at: str
    target: Literal["draft", "live"]
    results: list[TestResult]
    summary: ValidationSummary


class WorkflowTestRun(Out):
    status: Literal["completed", "stopped"]
    pauses_approved: int
    visited: list[str]
    output: str | None
    end_status: str | None


class Version(Out):
    version: int
    published_at: str
    published_by: str
    note: str
    changes: list[str]
    current: bool


class RunStep(Out):
    node_id: str
    label: str
    kind: Literal["trigger", "agent", "tool", "review", "action", "end"]
    status: Literal["done", "waiting", "failed", "skipped"]
    duration_ms: int
    detail: str | None = None


class WorkflowRun(Out):
    id: str
    workflow_id: str
    version: int
    subject: str
    status: Literal["completed", "waiting_review", "failed", "running"]
    started_at: str
    duration_ms: int
    review_id: str | None = None
    error: str | None = None
    trigger: str | None = None
    steps: list[RunStep]


# ── graphs ──


class GraphInput(Out):
    name: str
    label: str
    type: str
    required: bool


class GraphInfo(Out):
    name: str
    title: str
    kind: Literal["code", "agent", "definition"]
    built_in: bool
    latest_version: int | None
    input: list[GraphInput]


# ── threads ──


class ThreadCreated(Out):
    thread_id: str
    graph: str
    version: int | None = None
    digest: str | None = None
    created: bool


class ThreadView(Out):
    thread_id: str
    graph: str
    version: int | None
    metadata: dict[str, Any]
    status: str
    created_at: str
    updated_at: str


class SlaTimer(Out):
    timer_id: str
    kind: str
    node: str
    due_at: str | None
    fired_at: str | None
    cancelled_at: str | None
    attempts: int
    state: Literal["open", "fired", "cancelled", "failed"]


class SlaEvent(Out):
    event: str
    data: Any = None


class Sla(Out):
    timers: list[SlaTimer]
    events: list[SlaEvent]


class CostTotals(Out):
    calls: int
    input_tokens: int
    output_tokens: int
    cost: str


class BudgetCaps(Out):
    max_calls: int | None
    max_tokens: int | None
    max_cost: str | None


class ThreadState(Out):
    thread_id: str
    graph: str
    version: int | None
    digest: str | None
    status: str
    values: dict[str, Any]
    next: list[str]
    interrupt: dict[str, Any] | None
    sla: Sla | None
    cost: CostTotals | None
    budget: BudgetCaps | None


class RunJournalEntry(Out):
    run_id: str
    kind: str
    status: str
    created_at: str
    finished_at: str | None
    nodes: list[str]
    owner: str | None
    generation: int | None
    crashed: dict[str, Any] | None
    cost: CostTotals | None


class Migrated(Out):
    thread_id: str
    from_version: int | None
    to_version: int
    waiting_at: list[str]


class GraphVersion(Out):
    name: str
    version: int
    digest: str
    created_at: str


class GraphPublished(Out):
    name: str
    version: int
    digest: str


# The run stream: Server-Sent Events, one JSON event per `data:` line ({event, runId, seq, node?, data?}).
SSE_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {"description": "Server-Sent Events", "content": {"text/event-stream": {"schema": {"type": "string"}}}}
}


# ── reviews and cases (the console's facade) ──


class Evidence(Out):
    kind: str
    label: str
    detail: str


class ReviewOrigin(Out):
    """Where a review came from: a chat with an agent (the conversation to open), or a workflow run."""

    kind: Literal["chat", "workflow"]
    thread_id: str | None = None
    agent_name: str | None = None


class ThreadReview(Out):
    """A paused workflow or agent step as a console `Review`, pending or decided."""

    id: str
    title: str
    customer: str
    workflow_id: str
    workflow_name: str
    agent_slug: str
    kind: Literal["approval"]
    risk: Literal["critical", "high", "medium", "low"]
    confidence: float
    proposal: str
    action_tool: str
    currency: str
    policy: ReviewPolicy
    sla_minutes: int
    approvals: list[str]
    status: Literal["pending", "in_review", "approved", "rejected", "returned"]
    created_at: str
    reasoning: list[str]
    evidence: list[Evidence]
    # The operation needs two approvers, so approving asks for a step-up.
    step_up: bool
    origin: ReviewOrigin
    decided_at: str | None = None
    decision_reason: str | None = None
    # The resume value a decided review was recorded with.
    resume: dict[str, Any] | None = None


Review = ThreadReview | PublishReview


class ReviewStats(Out):
    unassigned: int
    median_decision_minutes: int
    median_decision_trend_minutes: int
    approved_as_proposed_rate: float
    decided_today: int


class ReviewList(ListResult[Review]):
    view_counts: dict[str, int]
    stats: ReviewStats


class BulkSkip(Out):
    id: str
    reason: str


class BulkResult(Out):
    updated: list[str]
    skipped: list[BulkSkip]


class CaseStep(Out):
    node_id: str
    label: str
    kind: str
    status: str
    duration_ms: int
    detail: str | None = None


class CaseRun(Out):
    """A workflow thread as the console's Cases `RunRow`."""

    id: str
    workflow_id: str
    workflow_name: str
    version: int
    subject: str
    status: Literal["completed", "waiting_review", "failed", "running"]
    started_at: str
    duration_ms: int
    review_id: str | None = None
    error: str | None = None
    trigger: str | None = None
    steps: list[CaseStep]
    state: Literal["running", "waiting", "failed", "done"]
    waiting_on: str | None
    queue: str | None
    assignee: str | None
    sla_due_at: str | None
    sla_minutes: int | None
    actions_approved: int
    actions_pending: int
    case_id: str | None


class CaseRunList(ListResult[CaseRun]):
    view_counts: dict[str, int]


# ── auth, approvals, deployments, inbox, timers, routing ──


class StepUpToken(Out):
    token: str
    expires_at: str


class Approval(Out):
    approvers: list[str]
    needed: int
    input_hash: str
    approval_token: str | None


class DeploymentView(Out):
    id: str
    graph: str
    channel: Literal["mailbox", "widget", "api", "mcp"]
    paused: bool
    multitask: Literal["enqueue", "reject"]
    budget: dict[str, Any] | None = None


class DeploymentPaused(Out):
    id: str
    paused: bool


class InboxPosted(Out):
    thread_id: str
    status: str
    seq: int | None


class InboxItem(Out):
    seq: int
    message_key: str
    kind: str
    status: str


class ThreadEventResult(Out):
    type: str
    restarted: list[dict[str, Any]]


class TimerFired(Out):
    timer_id: str
    status: str
    run_id: str | None
    attempts: int | None


class Routed(Out):
    thread_id: str
    status: str


class RoutedVersion(Out):
    workflow_id: str
    version_number: int
    threads: list[Routed]
