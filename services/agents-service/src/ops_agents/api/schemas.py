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

from ops_agents.activities.agent_limits import AgentLimits

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
    max_tool_calls_per_turn: int | None
    max_model_calls_per_turn: int | None = None
    max_model_calls_per_conversation: int | None = None
    max_cost_per_conversation: float | None = None
    when_unsure: Literal["handoff", "ask", "decline"]
    blocked_topics: list[str]


class UsedIn(Out):
    workflow_id: str
    workflow_name: str
    pinned_version: int
    status: Literal["live", "draft", "paused"]
    # The agent's own one-step workflow, which publishes with it (UX walk agents-2).
    own: bool | None = None


class GuardrailPin(Out):
    """A guardrail an agent version pins, with the version and the topics it blocks."""

    guardrail_id: str
    version: int
    name: str
    topics: list[str]
    # False when the builder switched it off on this version: it is not checked.
    enabled: bool


class AgentControls(Out):
    """What the runtime enforces; the console hides every other control."""

    channels: list[Literal["voice", "chat", "email", "api"]]
    guardrails: list[
        Literal[
            "redactPii",
            "maxToolCallsPerTurn",
            "maxModelCallsPerTurn",
            "maxModelCallsPerConversation",
            "maxCostPerConversation",
            "whenUnsure",
            "blockedTopics",
        ]
    ]
    evals: bool


class AgentRun(Out):
    """A thread the agent answered in: a chat, or a run of its own graph."""

    thread_id: str
    kind: Literal["chat", "graph"]
    title: str
    status: str
    version: int | None = None
    started_at: str
    updated_at: str


class WidgetTemplateOut(Out):
    """A published widget template version (c-082): its catalogue tree, its data schema and a sample to preview."""

    widget_id: str
    # The owning team's display name (api/team_names.py), on the detail response only; None when unread.
    team_name: str | None = None
    # What the caller may do with it (api/rights.py), on the detail response only.
    can_edit: bool | None = None
    can_delete: bool | None = None
    can_publish: bool | None = None
    version: int
    name: str
    use_when: str
    tree: dict[str, Any]
    data_schema: dict[str, Any]
    sample: dict[str, Any] | None = None
    # Tools the widget's buttons ask the agent to use; an agent pins it only when it holds them all.
    requires_tools: list[str] = Field(default_factory=list[str])
    # draft, in_review, published or deprecated (retired); the seeded library's are published.
    status: Literal["draft", "in_review", "published", "deprecated"] = "published"
    # Absent on the seeded library's platform-wide widgets.
    team_id: str | None = None
    updated_by: str | None = None
    updated_at: str | None = None


class WidgetTemplateList(ListResult[WidgetTemplateOut]):
    """GET /v1/widgets?page=: one page of the templates the caller sees, newest version each."""


class WidgetPin(Out):
    widget_id: str
    version: int
    name: str
    requires_tools: list[str] = Field(default_factory=list[str])


MEMORY_KINDS = ("fact", "preference", "episode")


class MemorySettings(Out):
    """What the agent remembers about each person (c-124): on by default (owner, 2026-10-17), and which kinds: facts
    (timezone, preferred account), preferences (how they like answers) and episodes (a line about each chat)."""

    enabled: bool = True
    kinds: list[Literal["fact", "preference", "episode"]] = Field(default_factory=lambda: list(MEMORY_KINDS))


class MemoryView(Out):
    """One thing an agent remembers about the caller (c-124)."""

    id: str
    agent_id: str
    agent_name: str
    kind: Literal["fact", "preference", "episode"]
    key: str | None = None
    value: str
    confidence: float
    # extraction (from a chat turn) or person (their correction).
    source: str
    source_thread_id: str | None = None
    created_at: str


class MemoryExport(Out):
    person: str
    memories: list[MemoryView]
    audit: list[dict[str, Any]]


class WidgetSettings(Out):
    """Whether the model may compose layouts from the catalogue, and how many widgets one answer may show (None: no
    cap; the agent's own setting is the only limit, owner Q4)."""

    compose: bool = False
    per_turn: int | None = Field(default=None, ge=1)


class Agent(Out):
    id: str
    # The owning team's display name (api/team_names.py), on the detail response only; None when unread.
    team_name: str | None = None
    # What the caller may do with it (api/rights.py), on the detail response only.
    can_edit: bool | None = None
    can_delete: bool | None = None
    can_publish: bool | None = None
    name: str
    # From the provisioning service (c-180): the template it was made from, and `system` or `managed`; null otherwise.
    template_id: str | None = None
    protection: Literal["system", "managed"] | None = None
    slug: str
    role: str
    instructions: str
    model: str
    channels: list[str]
    tool_ids: list[str]
    # Granted ids the tool directory no longer offers; the next save drops them.
    stale_tool_ids: list[str]
    collections: list[str]
    # The owning team, from the creator's token (c-171); null for an agent no team owns.
    team_id: str | None
    paused: bool
    availability: Literal["published", "not_published", "paused"]
    version: int
    published_version: int | None
    updated_at: str
    tasks24h: int = Field(alias="tasks24h")
    auto_resolved_rate: float
    workflow_ids: list[str]
    guardrails: Guardrails
    guardrail_pins: list[GuardrailPin]
    wrapper_workflow_id: str | None = None
    # What callers may override; defaults derived from the version when it was saved without limits.
    limits: AgentLimits
    # Widgets the agent may show in chat, and its composition and per-answer settings (c-082).
    widget_pins: list[WidgetPin] = Field(default_factory=list[WidgetPin])
    widgets: WidgetSettings = Field(default_factory=WidgetSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    controls: AgentControls
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
    # How the call went (c-170): ok, error, or gated (stopped for a review), so a failed call does not read as done.
    status: Literal["ok", "error", "gated", "running"] = "ok"
    access: str = "read"


class CitationView(Out):
    source: str
    section: str
    # Which knowledge base, page and words the reply cited (c-170).
    kb_id: str | None = None
    kb_name: str | None = None
    page: int | None = None
    quote: str | None = None


class KnowledgeBaseRef(Out):
    id: str
    name: str


class HeldTool(Out):
    """A tool the tested agent holds (c-170), and whether calling it pauses for a review, at which gate, for whom."""

    name: str
    access: str
    pauses: bool
    gate: str | None = None
    reviewers: str | None = None


class NamedRef(Out):
    name: str
    version: int | None = None


class BlockedBy(Out):
    name: str
    topic: str
    when: Literal["before", "after"]


class WouldPause(Out):
    gate: str
    reviewers: str
    # The approval a real run raises for the same call (c-068 T002): the tool, what it would do, and whether
    # deciding it needs a step-up.
    tool: str
    action: str
    step_up: bool


class AgentTestTurn(Out):
    reply: str
    tool_calls: list[ToolCallView]
    citations: list[CitationView]
    took_ms: int
    # The model alias the turn ran on: the agent's, or the runtime's when the agent names none.
    model: str
    would_pause: WouldPause | None = None
    # What the reply could use and did (c-170): the bases it searched, the tools it holds, and the skills and
    # guardrails the turn loaded and checked.
    knowledge_bases: list[KnowledgeBaseRef] = Field(default_factory=list[KnowledgeBaseRef])
    tools: list[HeldTool] = Field(default_factory=list[HeldTool])
    skills: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]])
    guardrails: list[NamedRef] = Field(default_factory=list[NamedRef])
    # The rule that refused the turn, when one did: before (the question, so the model never ran and nothing was
    # searched or loaded) or after (the answer, replaced by the rule's message). Absent on a turn no rule stopped.
    blocked_by: BlockedBy | None = None
    # Whether the turn searched its knowledge bases; false when a rule refused the question first.
    searched: bool = False


class Tool(Out):
    """A published tools-service operation an agent may be granted (`server` is its module's name), or a published
    workflow (`workflow:<id>`, access `workflow`, server `Workflows`)."""

    id: str
    name: str
    # What people see in place of the name: a plugin tool's manifest title; None for every other tool.
    title: str | None = None
    server: str
    module_id: str | None
    description: str
    access: Literal["read", "write", "workflow"]
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


class ReviewGuardrailPin(Out):
    guardrail_id: str
    version: int
    name: str
    enabled: bool


class PublishDecisionFields(Out):
    """What the team's publish policy said when the request was made (c-086); absent on requests made before it."""

    review_required: bool | None = None
    policy: Literal["always", "major", "never"] | None = None
    major_change: bool | None = None
    review_reason: (
        Literal["policy_always", "security_change", "policy_never", "major_change", "dev_auto_approve", "minor_change"]
        | None
    ) = None


class AgentPublishRequest(PublishDecisionFields):
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
    # Absent on requests opened before limits were reviewed with the agent (c-068).
    limits: AgentLimits | None = None
    # Each pinned guardrail and whether it is checked (c-085); absent on requests opened before the switch.
    guardrail_pins: list[ReviewGuardrailPin] | None = None


class ValidationSummary(Out):
    passed: int
    total: int
    regressions: int
    checks_failing: int


class PublishRequestInfo(PublishDecisionFields):
    workflow_id: str
    from_version: int
    to_version: int
    note: str
    requested_by: str
    changes: list[str]
    validation: ValidationSummary | None
    digest: str


class OperationSummary(Out):
    name: str
    method: str | None = None
    path: str | None = None
    access: str


class ChangedOperation(OperationSummary):
    # What changed: method, path, access, executor or inputs.
    fields: list[str]


class ToolModuleDiff(Out):
    """What a tool module review approves since the published version (c-204), as tools-service sent it when the
    review opened."""

    added: list[OperationSummary] = Field(default_factory=list[OperationSummary])
    removed: list[OperationSummary] = Field(default_factory=list[OperationSummary])
    changed: list[ChangedOperation] = Field(default_factory=list[ChangedOperation])
    hosts_added: list[str] = Field(default_factory=list[str])
    secrets: list[str] = Field(default_factory=list[str])


class ToolModuleReviewRef(Out):
    module_id: str
    version: str
    apply_pending: bool
    # Absent on a review copied from before c-204.
    diff: ToolModuleDiff | None = None


class PublishReview(Out):
    """The console's `Review` as a publish request carries it: `agent_publish` or `publish_request`."""

    id: str
    # Whether the caller may decide it now, by the same checks the decision route runs (c-123); absent outside Reviews.
    can_decide: bool | None = None
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
    # Minutes left before it is overdue, negative once overdue; null once decided.
    sla_minutes: int | None = None
    approvals: list[str]
    status: Literal["pending", "in_review", "approved", "rejected", "returned"]
    created_at: str
    decided_by: str | None = None
    decided_at: str | None = None
    decision_reason: str | None = None
    reasoning: list[str]
    evidence: list[Any]
    agent_publish: AgentPublishRequest | None = None
    publish: PublishRequestInfo | None = None
    tool_module: ToolModuleReviewRef | None = None
    # Who the review is assigned to now (c-074); None while nobody has it.
    assignee: str | None = None


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
    """What another service needs about a workflow: its id, name and owning team (internal route)."""

    id: str
    name: str
    team_id: str
    status: str


class Workflow(Out):
    id: str
    name: str
    description: str
    # The owning team, from the creator's token (c-171).
    team_id: str | None
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
    # v1 (a graph on /v1/graphs) or v2 (a runner definition on /v1/workflows/definitions); the list holds both.
    engine: Literal["v1", "v2"] = "v1"
    # How it starts, from its trigger (c-466); the list sets it on every row.
    start: WorkflowStart | None = None


class WorkflowStart(Out):
    # The start form's kind (email, form), or "source" for a trigger only its source starts (a service event).
    kind: str
    # Start run and Files offer it: its trigger declares a start form and other workflows are not its only starters.
    by_hand: bool
    # Its start form has a file field, so Files offers to start it with a file.
    takes_files: bool


class WorkflowDraft(Out):
    graph: WorkflowGraph
    saved_at: str
    saved_by: str


class WorkflowDetail(Workflow):
    graph: WorkflowGraph
    draft: WorkflowDraft | None = None
    # The owning team's display name (api/team_names.py), on the detail response only; None when unread.
    team_name: str | None = None
    # What the caller may do with it (api/rights.py), on the detail response only.
    can_edit: bool | None = None
    can_delete: bool | None = None
    can_publish: bool | None = None


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


class OptionInput(Out):
    """One input a reviewer may set when choosing an option, declared from the operation's input schema."""

    name: str
    type: str
    required: bool
    default: Any = None
    minimum: float | None = None
    maximum: float | None = None
    enum: list[Any] | None = None


class DecidingTeam(Out):
    """The team that decides a review: its writes' approving team, else the run's or thread's team."""

    id: str
    # Read live from platform-service (team_names.py); None when it cannot be read.
    name: str | None = None


class ActionField(Out):
    """One value a call would send, labelled from its operation's schema or reviewer card and formatted."""

    label: str
    value: str


class ReviewOption(Out):
    """One way to decide a step with options (c-057: a levy case's hold or flag): its call and the inputs the
    reviewer may set on it. A form renders from `inputs`; decide validates against them."""

    name: str
    inputs: list[OptionInput] = Field(default_factory=list[OptionInput])
    call: dict[str, Any] | None = None
    # Choosing this option asks the reviewer for a step-up (its call's policy).
    step_up: bool = False
    # The button's words, what choosing it does, and the values its call sends, in a reviewer's words (c-289).
    label: str | None = None
    consequence: str | None = None
    fields: list[ActionField] = Field(default_factory=list[ActionField])


class ReadField(Out):
    """One field a document read asks for, as the workflow's Extract from file step declares it."""

    key: str
    label: str
    type: str
    required: bool
    # The document type marks it key: the check asks a person to confirm it on its own before Approve.
    key_field: bool = False


class ReadCitation(Out):
    page: int | None
    quote: str | None


class ReadBox(Out):
    """Where a value sits on a page, as fractions of the page from its top left (documents-service, c-252)."""

    page: int
    x: float
    y: float
    w: float
    h: float


class FieldRead(Out):
    """One field of one record as read: the normalised value, what the model said, the confidence from the engine's
    checks, whether a person must check it, and where on the file it came from."""

    value: Any = None
    extracted_value: Any = None
    confidence: float | None
    needs_review: bool
    citation: ReadCitation | None
    boxes: list[ReadBox] = Field(default_factory=list[ReadBox])
    # When the step also combined this read with other sources (Combine facts, c-259): each source's value for the
    # field, and whether the sources disagree on it (c-261).
    by_source: dict[str, Any] | None = None
    conflict: bool = False


class ReadRecord(Out):
    values: dict[str, Any]
    fields: dict[str, FieldRead]


class DocumentRead(Out):
    """A document read a review asks a person to check (c-169): the file, the floor, and each record's fields. Editable
    when the step takes a correction (`inputs.edited`); `corrected` holds the values a decided review was approved
    with, None when no correction was sent."""

    file_id: str
    file_name: str | None
    floor: float | None
    schema_: list[ReadField] = Field(alias="schema")
    records: list[ReadRecord]
    editable: bool
    corrected: list[dict[str, Any]] | None
    # The sources a Combine facts step weighed against this read, in order; empty for a read of one source (c-261).
    sources: list[str] = Field(default_factory=list[str])


class ReplyCase(Out):
    run_id: str
    # None while that run has not opened its case yet.
    case_id: str | None
    # The case's subject, for the reviewer to read in place of its id (c-289); None until the case opens.
    subject: str | None = None


class ReplyPreview(Out):
    """The reply a review approves, as it will leave: to the sender, from the team's mailbox, with the cases the
    document opened (c-169)."""

    to: str
    mailbox: str | None
    subject: str
    body: str
    cases: list[ReplyCase]


class TaskTypeRef(Out):
    id: str
    version: int
    name: str


class TaskRegion(Out):
    # The type's regions, and `assist`: what task assist wrote for the task (c-302), marked AI in its data.
    region: Literal[
        "header", "why_source", "document", "facts", "write_preview", "form", "message", "history", "assist"
    ]
    collapsed: bool
    # Each slot of the region filled from the task's params (c-288); the console draws it, it never fills a template.
    data: dict[str, Any]


class TaskAction(Out):
    name: str
    label: str
    consequence: str | None
    reason: Literal["required", "optional", "none"]
    tone: Literal["primary", "neutral", "destructive"]
    # The step's out port the action leads to; the decision names it as its option.
    port: str
    inputs: list[dict[str, Any]]
    requires: str | None


class TaskWarning(Out):
    field: str
    severity: Literal["warning", "error"]
    message: str


class TypedTask(Out):
    """A review drawn from its task type (c-288): the type at the version the step pinned, its regions and actions
    bound to the step's params, and what is missing or of the wrong kind."""

    type: TaskTypeRef
    regions: list[TaskRegion]
    actions: list[TaskAction]
    warnings: list[TaskWarning]


class ThreadReview(Out):
    """A paused workflow or agent step as a console `Review`, pending or decided."""

    id: str
    # Whether the caller may decide it now, by the same checks the decision route runs (c-123); absent outside Reviews.
    can_decide: bool | None = None
    title: str
    customer: str
    workflow_id: str
    workflow_name: str
    # A workflow runner's step: its name and its run, for the sheet's subtitle and link (c-169); None elsewhere.
    step_name: str | None = None
    run_id: str | None = None
    # The workflow version the run pinned, so a reviewer knows which definition paused it (c-074).
    workflow_version: int | None = None
    # Who the review is assigned to now (c-074); None while nobody has it.
    assignee: str | None = None
    agent_slug: str
    kind: Literal["approval"]
    risk: Literal["critical", "high", "medium", "low"]
    # None for a step no model scored (a v2 workflow's review step).
    confidence: float | None
    proposal: str
    action_tool: str
    # The account's currency when the step read one; None rather than a guess when it did not.
    currency: str | None
    policy: ReviewPolicy
    # Minutes left before the step's deadline (its slaHours, else the workspace's), negative once past; null once
    # decided, or for a step paused before deadlines were recorded.
    sla_minutes: int | None
    # When the deadline falls; null as for sla_minutes.
    due_at: str | None = None
    approvals: list[str]
    status: Literal["pending", "in_review", "approved", "rejected", "returned"]
    created_at: str
    reasoning: list[str]
    evidence: list[Evidence]
    # The operation needs two approvers, so approving asks for a step-up.
    step_up: bool
    origin: ReviewOrigin
    decided_by: str | None = None
    decided_at: str | None = None
    decision_reason: str | None = None
    # The resume value a decided review was recorded with.
    resume: dict[str, Any] | None = None
    # What the proposal would move (the call input named amount), the options a step offers and the call behind
    # each, and the last failed call's error (a bank's 422 on a hold) the case waits on (c-057).
    amount: float | None = None
    options: list[ReviewOption] | None = None
    # Why the step's options could not be read (a row paused before declarations existed, on a version that no
    # longer declares them): the review is listed, never dropped or a 500.
    options_error: str | None = None
    calls: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    # The option a decided review was decided with; its status stays a ReviewStatus (approved).
    option: str | None = None
    # A fingerprint of the step-up a decided money review was made under; null when none was needed.
    step_up_ref: str | None = None
    # The case the review's run is on (c-128), so Human Tasks names it; None when the run is on no case.
    case_id: str | None = None
    # The case's subject, on a list grouped by case (c-460); None when the reader's teams do not hold the case.
    case_title: str | None = None
    # The document read the step asks a person to check, and the reply it approves (c-169); None on other reviews.
    read: DocumentRead | None = None
    reply: ReplyPreview | None = None
    # The one question the step asks, in a reviewer's words, and the file the decision is about (the first file id in
    # the run's input or the step's summary) (c-289).
    question: str | None = None
    source_file: str | None = None
    # The first call's consequence (its reviewer card's, when it has one) and the values it sends, worded.
    consequence: str | None = None
    action_fields: list[ActionField] = Field(default_factory=list[ActionField])
    # Who decides it, so the task names the deciding team (c-371); None on a review that predates it.
    deciding_team: DecidingTeam | None = None
    # The screen of a step that names a task type; None for a step that does not.
    task: TypedTask | None = None


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
    # A child case names its parent; a parent lists its children with their current outcome.
    parent_thread_id: str | None = None
    children: list[dict[str, Any]] | None = None


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
    channel: Literal["widget", "api", "mcp"]
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


class Routed(Out):
    thread_id: str
    status: str


class RoutedVersion(Out):
    workflow_id: str
    version_number: int
    threads: list[Routed]


class GuardrailConfig(Out):
    topics: list[str]
    message: str
    # Topic to what it covers and what it does not; absent when no topic has one.
    scopes: dict[str, str] | None = None
    # Shown only once checked; absent (off) streams the answer and replaces it on a hit.
    hold_until_checked: bool | None = None


class GuardrailVersion(Out):
    version: int
    config: GuardrailConfig
    state: Literal["draft", "published"]
    note: str
    saved_by: str
    saved_at: str
    published_at: str | None
    published_by: str | None


class Guardrail(Out):
    """A guardrail an agent pins by version (c-063); kind blocked_topics today."""

    id: str
    slug: str
    name: str
    kind: Literal["blocked_topics"]
    owner: str
    status: Literal["live", "deprecated"]
    version: int
    published_version: int | None
    config: GuardrailConfig
    used_by: list[str]
    # The open publish request, decided at /v1/guardrails/{id}/publish-requests/{requestId}/decision.
    pending_request_id: str | None
    versions: list[GuardrailVersion]
    updated_at: str


class GuardrailList(ListResult[Guardrail]):
    """GET /v1/guardrails?page=: one page of the guardrails, by name."""


# ── skills (spec 11; console lib/types/skills.ts) ──


class SkillToolRef(Out):
    tool_id: str
    name: str
    module: str
    system: str
    access: str


class SkillContent(Out):
    name: str
    slug: str
    use_when: str
    loading: Literal["on_match", "always"]
    instructions: str
    tools: list[SkillToolRef]
    knowledge_bases: list[str]
    guardrails: list[str]
    resources: list[dict[str, Any]]
    # What the agent says when one of the skill's guardrails refuses; absent uses the platform's sentence.
    refusal: str | None = None


class Skill(Out):
    id: str
    name: str
    slug: str
    use_when: str
    loading: Literal["on_match", "always"]
    owner_team: str
    status: Literal["draft", "in_review", "published", "deprecated"]
    version: int
    published_version: int | None
    draft_version: int | None
    used_by: int
    live_agents: int
    tool_count: int
    kb_count: int
    last_eval_pass_rate: float | None
    tokens: int
    updated_at: str
    updated_by: str
    origin: Literal["blank", "generated", "imported", "duplicated"]
    pending_review_id: str | None = None


class SkillVersion(Out):
    version: int
    state: Literal["draft", "in_review", "published", "superseded", "deprecated", "rejected"]
    edit_class: Literal["free", "re_test", "re_approval"]
    note: str
    changes: list[str]
    saved_by: str
    saved_at: str
    content: SkillContent
    tokens: int
    review_id: str | None = None
    published_at: str | None = None
    published_by: str | None = None
    test_run: dict[str, Any] | None


class SkillUsage(Out):
    agent_id: str
    agent_name: str
    agent_team_id: str | None
    agent_availability: Literal["published", "not_published", "paused"]
    pinned_version: int
    latest_published: int | None
    upgrade_available: bool
    upgrade_blocked: str | None = None
    loads7d: int = Field(alias="loads7d")
    share7d: float = Field(alias="share7d")
    last_loaded_at: str | None
    attached_at: str
    attached_by: str


class SkillPublishCheck(Out):
    can_request: bool
    blockers: list[str]
    edit_class: Literal["free", "re_test", "re_approval"]
    approvers_needed: int


class SkillDetail(Skill):
    content: SkillContent
    versions: list[SkillVersion]
    tests: list[dict[str, Any]]
    runs: list[dict[str, Any]]
    usage: list[SkillUsage]
    activity: dict[str, Any]
    provenance: dict[str, Any]
    pending_review: dict[str, Any] | None = None
    publish_check: SkillPublishCheck


class SkillList(ListResult[Skill]):
    view_counts: dict[str, int]


class AgentSkillPin(Out):
    skill_id: str
    name: str
    use_when: str
    loading: Literal["on_match", "always"]
    pinned_version: int
    latest_published: int | None
    status: Literal["draft", "in_review", "published", "deprecated"]
    upgrade_available: bool
    upgrade_blocked: str | None = None
    loads7d: int = Field(alias="loads7d")
    share7d: float = Field(alias="share7d")
    tokens: int


class AttachableSkill(Out):
    skill_id: str
    name: str
    use_when: str
    loading: Literal["on_match", "always"]
    latest_published: int
    owner_team: str
    attachable: bool
    missing: list[str]


class AgentSkills(Out):
    agent_id: str
    pins: list[AgentSkillPin]
    available: list[AttachableSkill]
    limits: dict[str, int]


class SkillOptions(Out):
    teams: list[str]
    tools: list[SkillToolRef]
    knowledge_bases: list[str]
    limits: dict[str, int]
