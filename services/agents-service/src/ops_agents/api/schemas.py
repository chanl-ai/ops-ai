"""Response models for the OpenAPI document: the envelope, the error, list pages, and the console contract types the
registry routes return (apps/console/src/lib/types/domain.ts).

Routes build their JSON by hand and return it through `ok()`, so FastAPI documents these models without validating
against them. The API tests close that gap: every response they receive is validated against its route's declared
model (tests/contract.py), and the models refuse unknown fields, so a field added to a route and not to its model
fails a test.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from ops_agent_kernel.prompt_writer import titled
from ops_agent_kernel.steps import IfNot, Jump, Ref, ReturnField, StepCheck
from ops_agents.activities.agent_limits import AgentLimits

# The envelope models live in ops_service_kit.http; the routers keep importing them from here.
from ops_service_kit.http import (
    Envelope,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    ErrorBody,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    ErrorEnvelope,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    ExternalOut,
    Json,
    JsonValue,
    ListResult,
    Option,
    OptionsPage,
    Out,
    Pagination,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    error_responses,
)

from .assurance_schemas import GateStep

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
    # `email` when the workflow starts from an email, so the agent's Channels tab lists it under Email.
    channel: Literal["email"] | None = None


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
    """A published widget template version: its catalogue tree, its data schema and a sample to preview."""

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
    # Documents the team authors in the widget builder: the layout tree, its JSON Schema and a sample record.
    tree: dict[str, JsonValue]
    data_schema: dict[str, JsonValue]
    sample: dict[str, JsonValue] | None = None
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
    """What the agent remembers about each person: on by default, and which kinds: facts
    (timezone, preferred account), preferences (how they like answers) and episodes (a line about each chat)."""

    enabled: bool = True
    kinds: list[Literal["fact", "preference", "episode"]] = Field(default_factory=lambda: list(MEMORY_KINDS))


class MemoryView(Out):
    """One thing an agent remembers about the caller."""

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
    audit: list[dict[str, JsonValue]]


class WidgetSettings(Out):
    """Whether the model may compose layouts from the catalogue, and how many widgets one answer may show (None: no
    cap; the agent's own setting is the only limit, owner Q4)."""

    compose: bool = False
    per_turn: int | None = Field(default=None, ge=1)


class BriefSectionView(Out):
    """A section added to a brief, as replied: `kind` is the id of a menu section in the workspace's list (the tag
    evals read) or `custom`; `name` is the heading it was saved under."""

    kind: str
    name: str = ""
    text: str = ""

    @model_validator(mode="before")
    @classmethod
    def _titled(cls, data: object) -> object:
        return titled(data)


class BriefView(Out):
    """An agent's brief as replied (`ops_agent_kernel.prompt_writer.Brief` is the request form)."""

    purpose: str
    goal: str = ""
    how_to_answer: str = ""
    hand_off: list[str] = Field(default_factory=list[str])
    examples: str = ""
    never: list[str] = Field(default_factory=list[str])
    success: list[str] = Field(default_factory=list[str])
    # Empty on a brief stored before sections.
    sections: list[BriefSectionView] = Field(default_factory=list[BriefSectionView])


class PatternsView(Out):
    """How the agent's turn runs, as replied (`Patterns` is the request form)."""

    thinking: Literal["default", "low", "medium", "high"] = "default"
    parallel_reads: bool = True


class AgentUses(Out):
    """How many of each kind the agent holds, for the page's one-line summary."""

    tools: int = 0
    knowledge_bases: int = 0
    skills: int = 0
    agents: int = 0
    workflows: int = 0


class Agent(Out):
    id: str
    # The owning team's display name (api/team_names.py), on the detail response only; None when unread.
    team_name: str | None = None
    # What the caller may do with it (api/rights.py), on the detail response only.
    can_edit: bool | None = None
    can_delete: bool | None = None
    can_publish: bool | None = None
    # With `version`, the copy a save names as its base (`baseVersion`, `baseDigest`); on the detail response only.
    digest: str | None = None
    name: str
    # From the provisioning service: the template it was made from, and `system` or `managed`; null otherwise.
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
    all_team_knowledge_bases: bool = False
    # Which skills a person may pick in a chat with this agent: team, attached or off.
    skill_menu: Literal["team", "attached", "off"] = "team"
    # The team account each app's calls use, app id to account name; empty for each app's default.
    accounts: dict[str, str] = Field(default_factory=dict[str, str])
    # The owning team, from the creator's token; null for an agent no team owns.
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
    # Widgets the agent may show in chat, and its composition and per-answer settings.
    widget_pins: list[WidgetPin] = Field(default_factory=list[WidgetPin])
    widgets: WidgetSettings = Field(default_factory=WidgetSettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    # The agent written as a brief; null on a version saved before the brief, which runs on `instructions` as it is.
    brief: BriefView | None = None
    # brief: the prompt is written from the brief. full: the builder's own instructions, with the never rules last.
    prompt_mode: Literal["brief", "full"] | None = None
    patterns: PatternsView = Field(default_factory=PatternsView)
    # The model settings the version saved, by knob name; empty runs on the model's defaults.
    model_settings: dict[str, float | int | str] = Field(default_factory=dict[str, float | int | str])
    uses: AgentUses = Field(default_factory=AgentUses)
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
    # How the call went: ok, error, or gated (stopped for a review), so a failed call does not read as done.
    status: Literal["ok", "error", "gated", "running"] = "ok"
    access: str = "read"


class CitationView(Out):
    source: str
    section: str
    # Which knowledge base, page and words the reply cited.
    kb_id: str | None = None
    kb_name: str | None = None
    page: int | None = None
    quote: str | None = None


class KnowledgeBaseRef(Out):
    id: str
    name: str


class HeldTool(Out):
    """A tool the tested agent holds, and whether calling it pauses for a review, at which gate, for whom."""

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
    # The approval a real run raises for the same call: the tool, what it would do, and whether
    # deciding it needs a step-up.
    tool: str
    action: str
    step_up: bool


class EvalCheckResult(Out):
    label: str
    status: Literal["pass", "fail"]
    # A judge check's one-line reason, or why the judge did not answer; absent on the string checks.
    reason: str | None = None
    # The judge's confidence; not asked for yet, so null.
    confidence: float | None = None


class EvalCaseOutcome(Out):
    status: Literal["pass", "fail"]
    reply: str
    checks: list[EvalCheckResult]
    latency_ms: int


class EvalCaseResult(Out):
    case_name: str
    draft: EvalCaseOutcome
    live: EvalCaseOutcome | None = None
    regression: bool = False
    # An alias this case's turns or judge spent tokens on has no price (absent on runs kept before it was recorded).
    unpriced: bool = False
    # The judge's alias spent tokens and has no price; false on a case with no judge check (absent on runs kept before).
    judge_unpriced: bool = False


class EvalSummary(Out):
    passed: int
    total: int
    regressions: int


class EvalGateDetails(Out):
    steps: list[GateStep]


class EvalGate(Out):
    """Whether the version a run scored may publish on its evals, and each step, as a publish check reads it."""

    blocked: bool
    steps: list[GateStep]


class AgentEvalRun(Out):
    """Cases sent in the body, scored and not kept."""

    id: str
    agent_id: str
    status: Literal["complete"]
    summary: EvalSummary
    results: list[EvalCaseResult]
    # Every turn's and judge call's tokens priced by alias (OPS_PRICES); `unpriced` when an alias that spent tokens
    # has no price, so its tokens count as 0.
    cost_usd: float
    unpriced: bool


class EvalRunRow(Out):
    """A kept run as a row of an agent's runs list (`app.evals.stored_run`): everything but the case results, which
    the single read (`EvalRunRecord`) carries. `version` is the newest version it ran on and `live_version` the live
    one it was compared with, when that was another. `trigger` is manual or publish_request; `started_by` is a
    person's email or `key:<id>`."""

    id: str
    agent_id: str
    version: int
    live_version: int | None
    trigger: str
    status: Literal["complete"]
    summary: EvalSummary
    cost_usd: float
    unpriced: bool
    started_by: str
    ran_at: str


class EvalRunRecord(EvalRunRow):
    """One kept run with each case's result."""

    results: list[EvalCaseResult]
    # Only on the reply of the run that was just made (`run_saved`); the CLI exits on it.
    gate: EvalGate | None = None


class LoadedSkill(Out):
    """A skill a turn loaded, as the kernel journals it (`skills.loaded_entry`); part and inputs are left out when
    there are none."""

    skill_id: str
    name: str
    version: int
    matched: str
    part: str | None = None
    inputs: dict[str, str] | None = None


class TurnUsage(Out):
    """Tokens one test turn spent, on the alias it ran on."""

    input_tokens: int
    output_tokens: int
    model: str


class AgentTestTurn(Out):
    reply: str
    tool_calls: list[ToolCallView]
    citations: list[CitationView]
    took_ms: int
    # The model alias the turn ran on: the agent's, or the runtime's when the agent names none.
    model: str
    usage: TurnUsage
    would_pause: WouldPause | None = None
    # What the reply could use and did: the bases it searched, the tools it holds, and the skills and
    # guardrails the turn loaded and checked.
    knowledge_bases: list[KnowledgeBaseRef] = Field(default_factory=list[KnowledgeBaseRef])
    tools: list[HeldTool] = Field(default_factory=list[HeldTool])
    skills: list[LoadedSkill] = Field(default_factory=list[LoadedSkill])
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
    # The tool's JSON Schema, as the app or module declared it.
    input_schema: dict[str, JsonValue]
    requires_approval: bool
    approval: str | None


class ToolApp(Out):
    id: str
    name: str


class ToolUserRef(Out):
    id: str
    name: str


class ToolUsedBy(Out):
    agents: list[ToolUserRef]
    workflows: list[ToolUserRef]


class ToolRow(Tool):
    """One tool on the Tools page, joined here: the app it belongs to, what kind of tool it is, whether the person
    asking can run it now, and the team's agents and workflows that use it."""

    # The app the tool's set belongs to; a builder's own tool set is its own app (`module:<id>`). None for a workflow
    # or an agent offered as a tool.
    app: ToolApp | None
    kind: Literal["app", "custom", "workflow", "agent"]
    # ready; needs_approval (its calls wait for an approver); app_not_connected (the team account is not signed in);
    # needs_your_sign_in (the app signs each person in and the person asking has not).
    status: Literal["ready", "needs_approval", "app_not_connected", "needs_your_sign_in"]
    used_by: ToolUsedBy


class ToolList(ListResult[ToolRow]):
    # The name of each app `facets.app` counts, by its id, so the App filter reads names the API joined.
    app_names: dict[str, str]


class ToolsNotAdded(Out):
    """An app whose catalog holds tools the team has not added: the picker cannot offer them, so it says how many wait
    on the app's Tools tab."""

    app_id: str
    name: str
    count: int


class ToolOption(Option):
    """A tool in a picker; an MCP link's picker (`agents=false`) also gets what the tool takes and what it does, which
    the link keeps so an assistant reads a workflow's inputs in tools/list."""

    input_schema: dict[str, JsonValue] | None = None
    description: str | None = None


class ToolOptionsPage(OptionsPage):
    data: list[ToolOption]  # pyright: ignore[reportIncompatibleVariableOverride]
    # The apps matching the search with tools not added, on a first page only; empty when the tools service is down.
    not_added: list[ToolsNotAdded] = Field(default_factory=list[ToolsNotAdded])


class AgentToolAppMatch(Out):
    """One of an app's tools whose words match the search, so the picker can offer it under its app."""

    id: str
    label: str
    access: str
    granted: bool


class AgentToolApp(Out):
    """An app as an agent's tools picker shows it: its state for the person asking, and how many of its tools the team
    added and the agent holds. A tool with no app card groups under its module, or under Workflows or Agents."""

    id: str
    name: str
    # `other` holds the agent's grants that nothing offers now (a paused agent, or any tool while tools-service is
    # down), so each can still be removed.
    kind: Literal["plugin", "builtin", "custom", "workflows", "agents", "other"]
    connected: bool
    # The app card's state as tools-service sends it, which the console's app state badge draws; none with no card.
    app_state: str | None = None
    # tools-service's group for the app (`on`, `needs_you`, `needs_admin`, ...); none for a group with no app card.
    app_group: str | None = None
    sign_in: str | None = None
    # Every tool the app has; the tools the team added, which an agent may be granted; the ones this agent holds.
    tools_total: int
    tools_offered: int
    tools_granted: int
    # The app's tools the team has not added, which the agent cannot be granted here: total less offered, at least 0.
    not_added: int
    # At most five, the first by label, and only when the search matched a tool's words.
    matches: list[AgentToolAppMatch]


class AgentToolAppsPage(OptionsPage):
    data: list[AgentToolApp]  # pyright: ignore[reportIncompatibleVariableOverride]


class AppTool(Out):
    """One of an app's tools the team added, and whether this agent holds it."""

    id: str
    label: str
    description: str
    access: str
    requires_approval: bool
    approval: str | None = None
    granted: bool


class AppToolsPage(OptionsPage):
    data: list[AppTool]  # pyright: ignore[reportIncompatibleVariableOverride]


class PromptVariable(Out):
    """A `{key}` an agent's instructions may name, filled at run time from the turn's variables."""

    key: str
    label: str
    example: str
    source: str


class ModelAlias(Out):
    """A chat alias an agent may name. Clearance and prices come from models-service; without it the runtime's own
    alias is listed by name alone."""

    name: str
    kind: Literal["chat"]
    cleared_sensitivity: str | None = None
    input_per_million: str | None = None
    output_per_million: str | None = None


class ModelAliasKnobs(Out):
    """The settings an agent on the alias may save, from models-service: `knobs` is a JSON Schema object of only the
    knobs the alias's model takes, each with its type, title, description, range and catalog default."""

    alias: str
    version: int
    model_id: str
    catalogued: bool
    knobs: Json


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
    """What the team's publish policy said when the request was made; absent on requests made before it."""

    review_required: bool | None = None
    policy: Literal["always", "major", "never"] | None = None
    major_change: bool | None = None
    review_reason: (
        Literal["policy_always", "security_change", "policy_never", "major_change", "dev_auto_approve", "minor_change"]
        | None
    ) = None


class InjectionTally(Out):
    passed: int
    total: int
    regressions: int


class PublishEvalSummary(Out):
    """An eval run against one agent version, as a publish request shows it. Nothing sends one yet: both are null."""

    run_id: str
    ran_at: str
    passed: int
    total: int
    regressions: int
    injection: InjectionTally


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
    candidate: PublishEvalSummary | None = None
    published: PublishEvalSummary | None = None
    failing: int
    blockers: list[str]
    changes: list[str]
    # Absent on requests opened before limits were reviewed with the agent.
    limits: AgentLimits | None = None
    # Each pinned guardrail and whether it is checked; absent on requests opened before the switch.
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


class SkillPublishAgent(Out):
    name: str
    pinned_version: int | None


class TextHint(Out):
    """A hint the reader put on one line of a skill's text (from 1)."""

    line: int
    message: str


class SkillPublishInfo(Out):
    """A skill publish request as its reviewer reads it, kept as it was when the request opened: the published
    version it replaces, both texts, the hints on the new text and what it adds."""

    skill_id: str
    skill_name: str
    # The owning team's id, and its name as platform-service names it (None when it cannot be read).
    owner_team: str
    owner_team_name: str | None = None
    from_version: int | None
    to_version: int
    edit_class: str
    requested_by: str
    note: str
    changes: list[str]
    # Skill tests are not run yet: always null and empty.
    test_run: None = None
    failing: list[str]
    tools_added: list[str]
    kbs_added: list[str]
    guardrails: list[str]
    agents: list[SkillPublishAgent]
    approvals_needed: int
    # Absent on a request opened before the texts were kept with it.
    text_before: str | None = None
    text_after: str | None = None
    hints: list[TextHint]


class OperationSummary(Out):
    name: str
    method: str | None = None
    path: str | None = None
    access: str


class ChangedOperation(OperationSummary):
    # What changed: method, path, access, executor or inputs.
    fields: list[str]


class ToolModuleDiff(Out):
    """What a tool module review approves since the published version, as tools-service sent it when the
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
    # Absent on a review copied from an older version.
    diff: ToolModuleDiff | None = None


class EgressHostRef(Out):
    """An app's address on a host nobody listed: the host, the app, who set it and their team."""

    host: str
    app: str
    requested_by: str
    team_id: str
    # The approval did not reach tools-service yet; the next read of the request applies it again.
    apply_pending: bool


class Evidence(Out):
    kind: str
    label: str
    detail: str


class PublishReview(Out):
    """The console's `Review` as a publish request carries it: `agent_publish` or `publish_request`."""

    id: str
    # Whether the caller may decide it now, by the same checks the decision route runs; absent outside Reviews.
    can_decide: bool | None = None
    # What the caller may do with it now, each by the check its own route runs (hitl_facade.for_viewer): assign an
    # unassigned task, reassign an assigned one, return it to who asked; absent outside Reviews.
    can_assign: bool | None = None
    can_reassign: bool | None = None
    can_return: bool | None = None
    # How many distinct people approve it, and whether the caller is already one of `approvals`.
    approvals_needed: int = 1
    viewer_approved: bool | None = None
    title: str
    customer: str
    workflow_id: str
    workflow_name: str
    agent_slug: str
    agent_name: str | None
    # egress_host: an app's first address on a host the tenant has not listed, for a Security admin.
    kind: Literal["agent_publish", "publish_request", "skill_publish", "egress_host"]
    risk: Literal["critical", "high", "medium", "low"]
    confidence: float
    proposal: str
    action_tool: str
    currency: str
    policy: ReviewPolicy
    # Minutes left before it is overdue, negative once overdue; null once decided.
    sla_minutes: int | None = None
    approvals: list[str]
    status: Literal["pending", "in_review", "approved", "rejected", "returned", "withdrawn"]
    created_at: str
    # The withdrawn request this one sends again; its comments carry over.
    follows: str | None = None
    decided_by: str | None = None
    decided_at: str | None = None
    decision_reason: str | None = None
    reasoning: list[str]
    evidence: list[Evidence]
    agent_publish: AgentPublishRequest | None = None
    publish: PublishRequestInfo | None = None
    skill_publish: SkillPublishInfo | None = None
    tool_module: ToolModuleReviewRef | None = None
    egress_host: EgressHostRef | None = None
    # Who the review is assigned to now; None while nobody has it.
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
    # The node's settings, which its node type defines (the engine's node registry).
    data: dict[str, JsonValue]
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


class WorkflowStart(Out):
    # The start form's kind (email, form), or "source" for a trigger only its source starts (a service event).
    kind: str
    # Start run and Files offer it: its trigger declares a start form and other workflows are not its only starters.
    by_hand: bool
    # Its start form has a file field, so Files offers to start it with a file.
    takes_files: bool


class Workflow(Out):
    id: str
    name: str
    description: str
    # The owning team, from the creator's token.
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
    # How it starts, from its trigger; the list sets it on every row.
    start: WorkflowStart | None = None


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
    metadata: dict[str, JsonValue]
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
    data: JsonValue = None


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
    values: dict[str, JsonValue]
    next: list[str]
    interrupt: dict[str, JsonValue] | None
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
    crashed: dict[str, JsonValue] | None
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
SSE_RESPONSE: dict[int | str, Json] = {
    200: {"description": "Server-Sent Events", "content": {"text/event-stream": {"schema": {"type": "string"}}}}
}


# ── reviews and cases (the console's facade) ──


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
    default: JsonValue = None
    minimum: float | None = None
    maximum: float | None = None
    enum: list[JsonValue] | None = None


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
    """One way to decide a step with options (a levy case's hold or flag): its call and the inputs the
    reviewer may set on it. A form renders from `inputs`; decide validates against them."""

    name: str
    inputs: list[OptionInput] = Field(default_factory=list[OptionInput])
    call: dict[str, JsonValue] | None = None
    # Choosing this option asks the reviewer for a step-up (its call's policy).
    step_up: bool = False
    # The button's words, what choosing it does, and the values its call sends, in a reviewer's words.
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
    """Where a value sits on a page, as fractions of the page from its top left (documents-service)."""

    page: int
    x: float
    y: float
    w: float
    h: float


class FieldRead(Out):
    """One field of one record as read: the normalised value, what the model said, the confidence from the engine's
    checks, whether a person must check it, and where on the file it came from."""

    value: JsonValue = None
    extracted_value: JsonValue = None
    confidence: float | None
    needs_review: bool
    citation: ReadCitation | None
    boxes: list[ReadBox] = Field(default_factory=list[ReadBox])
    # When the step also combined this read with other sources (Combine facts): each source's value for the
    # field, and whether the sources disagree on it.
    by_source: dict[str, JsonValue] | None = None
    conflict: bool = False


class ReadRecord(Out):
    values: dict[str, JsonValue]
    fields: dict[str, FieldRead]


class DocumentRead(Out):
    """A document read a review asks a person to check: the file, the floor, and each record's fields. Editable
    when the step takes a correction (`inputs.edited`); `corrected` holds the values a decided review was approved
    with, None when no correction was sent."""

    file_id: str
    file_name: str | None
    floor: float | None
    schema_: list[ReadField] = Field(alias="schema")
    records: list[ReadRecord]
    editable: bool
    corrected: list[dict[str, JsonValue]] | None
    # The sources a Combine facts step weighed against this read, in order; empty for a read of one source.
    sources: list[str] = Field(default_factory=list[str])


class ReplyCase(Out):
    run_id: str
    # None while that run has not opened its case yet.
    case_id: str | None
    # The case's subject, for the reviewer to read in place of its id; None until the case opens.
    subject: str | None = None


class ReplyPreview(Out):
    """The reply a review approves, as it will leave: to the sender, from the team's mailbox, with the cases the
    document opened."""

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
    # The type's regions, and `assist`: what task assist wrote for the task, marked AI in its data.
    region: Literal[
        "header", "why_source", "document", "facts", "write_preview", "form", "message", "history", "assist"
    ]
    collapsed: bool
    # Each slot of the region filled from the task's params; the console draws it, it never fills a template.
    data: dict[str, JsonValue]


class TaskAction(Out):
    name: str
    label: str
    consequence: str | None
    reason: Literal["required", "optional", "none"]
    tone: Literal["primary", "neutral", "destructive"]
    # The step's out port the action leads to; the decision names it as its option.
    port: str
    inputs: list[dict[str, JsonValue]]
    requires: str | None


class TaskWarning(Out):
    field: str
    severity: Literal["warning", "error"]
    message: str


class TypedTask(Out):
    """A review drawn from its task type: the type at the version the step pinned, its regions and actions
    bound to the step's params, and what is missing or of the wrong kind."""

    type: TaskTypeRef
    regions: list[TaskRegion]
    actions: list[TaskAction]
    warnings: list[TaskWarning]


class ConnectWait(Out):
    """What a run waiting for a person's own account of an app needs: Connect my account, or Run as the
    team account where the app has one."""

    app: str
    connection_id: str | None = None
    # The account's app, under which Connect my account opens it.
    app_id: str | None = None
    # The person whose account the run waits for: the run's starter.
    person: str | None = None
    team_account: bool = False


class ThreadReview(Out):
    """A paused workflow or agent step as a console `Review`, pending or decided."""

    id: str
    # Whether the caller may decide it now, by the same checks the decision route runs; absent outside Reviews.
    can_decide: bool | None = None
    # What the caller may do with it now, each by the check its own route runs (hitl_facade.for_viewer): assign an
    # unassigned task, reassign an assigned one, return it to who asked; absent outside Reviews.
    can_assign: bool | None = None
    can_reassign: bool | None = None
    can_return: bool | None = None
    # How many distinct people approve it, and whether the caller is already one of `approvals`.
    approvals_needed: int = 1
    viewer_approved: bool | None = None
    title: str
    customer: str
    workflow_id: str
    workflow_name: str
    # A workflow runner's step: its name and its run, for the sheet's subtitle and link; None elsewhere.
    step_name: str | None = None
    # What approving runs, in a reviewer's words ("Place hold"), never the tool's id; None when the step sends no call.
    action_label: str | None = None
    run_id: str | None = None
    # The workflow version the run pinned, so a reviewer knows which definition paused it.
    workflow_version: int | None = None
    # Who the review is assigned to now; None while nobody has it.
    assignee: str | None = None
    agent_slug: str
    # connect_account: a run waiting for the person it acts for to connect their own account of an app.
    kind: Literal["approval", "connect_account"]
    # The app and the person a connect_account task asks; None on every other review.
    connect: ConnectWait | None = None
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
    status: Literal["pending", "in_review", "approved", "rejected", "returned", "withdrawn"]
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
    resume: dict[str, JsonValue] | None = None
    # What the proposal would move (the call input named amount), the options a step offers and the call behind
    # each, and the last failed call's error (a bank's 422 on a hold) the case waits on.
    amount: float | None = None
    options: list[ReviewOption] | None = None
    # Why the step's options could not be read (a row paused before declarations existed, on a version that no
    # longer declares them): the review is listed, never dropped or a 500.
    options_error: str | None = None
    # An app's call input and its error body come from the workflow and the outside system, so they stay JSON.
    calls: dict[str, JsonValue] | None = None
    error: dict[str, JsonValue] | None = None
    # The option a decided review was decided with; its status stays a ReviewStatus (approved).
    option: str | None = None
    # A fingerprint of the step-up a decided money review was made under; null when none was needed.
    step_up_ref: str | None = None
    # The case the review's run is on, so Human Tasks names it; None when the run is on no case.
    case_id: str | None = None
    # The case's subject, on a list grouped by case; None when the reader's teams do not hold the case.
    case_title: str | None = None
    # The document read the step asks a person to check, and the reply it approves; None on other reviews.
    read: DocumentRead | None = None
    reply: ReplyPreview | None = None
    # The one question the step asks, in a reviewer's words, and the file the decision is about (the first file id in
    # the run's input or the step's summary).
    question: str | None = None
    source_file: str | None = None
    # The first call's consequence (its reviewer card's, when it has one) and the values it sends, worded.
    consequence: str | None = None
    action_fields: list[ActionField] = Field(default_factory=list[ActionField])
    # Who decides it, so the task names the deciding team; None on a review that predates it.
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
    # Each child run's outcome as the workflow recorded it.
    children: list[dict[str, JsonValue]] | None = None


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


class DeploymentBudget(ExternalOut):
    """Caps for the thread a deployment starts; stored as the request gave them, so the names stay snake_case."""

    max_calls: int | None = None
    max_tokens: int | None = None
    max_cost: Decimal | None = None


class DeploymentView(Out):
    id: str
    graph: str
    channel: Literal["widget", "api", "mcp"]
    paused: bool
    multitask: Literal["enqueue", "reject"]
    budget: DeploymentBudget | None = None


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


class TimerRestart(Out):
    timer_id: str
    kind: str
    due_at: str


class ThreadEventResult(Out):
    type: str
    restarted: list[TimerRestart]


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
    """A guardrail an agent pins by version; kind blocked_topics today."""

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


class SkillInputField(Out):
    """One value a person or assistant gives when using the skill; an MCP client asks for it as a prompt argument."""

    name: str
    type: Literal["string"] = "string"
    description: str = ""
    required: bool = False


class SkillPart(Out):
    """One named part of a skill, read with the skill's shared instructions (`salesforce/prepare-meeting`)."""

    slug: str
    name: str
    use_when: str
    instructions: str
    inputs: list[SkillInputField] = Field(default_factory=list[SkillInputField])
    # Some of the skill's own tools; absent when the part names none.
    tool_ids: list[str] = Field(default_factory=list[str])
    # The most tokens the part may hold when loaded; absent takes the reply's whole skill budget.
    budget: int | None = None


class SkillPartSummary(Out):
    """A part as a list row carries it: enough for a menu or an MCP prompt without a read per skill."""

    slug: str
    name: str
    use_when: str
    inputs: list[SkillInputField] = Field(default_factory=list[SkillInputField])


class SkillResource(Out):
    """A file or a text template kept on a skill version; a file is stored through the Files API."""

    id: str
    kind: Literal["file", "template"]
    name: str
    description: str | None = None
    file_id: str | None = None
    size: int | None = None
    # Set while the file is quarantined or unscanned: the skill loads without it.
    blocked: str | None = None
    body: str | None = None
    added_at: str
    added_by: str


# A skill's steps as a reply carries them. The fields and their limits are the ones a save takes
# (ops_contracts.skill_run); these add only what makes each a reply model.
class RefOut(Out, Ref):
    pass


class StepCheckOut(Out, StepCheck):
    pass


class IfNotOut(Out, IfNot):
    pass


class JumpOut(Out, Jump):
    pass


class BranchOut(Out):
    """A path written `if <test>:`: when the test does not hold, the skill goes to `otherwise`."""

    test: StepCheckOut
    otherwise: JumpOut


class SkillStepOut(Out):
    """One step: what to do, what it runs, what must hold after it and what happens when it does not."""

    do: str
    use: RefOut | None = None
    check: StepCheckOut | None = None
    if_not: IfNotOut | None = None
    branch: BranchOut | None = None
    # Where the skill goes once the step is done, when that is not the step after it.
    next: JumpOut | None = None
    locked: bool | None = Field(
        default=None,
        description="True when the builder locked the step's tool to this step: the agent reaches it only as the "
        "step, even when it is a read. Absent otherwise; a tool that changes something is kept to its step either way.",
    )


class ReturnFieldOut(Out, ReturnField):
    pass


class SkillContent(Out):
    name: str
    slug: str
    use_when: str
    loading: Literal["on_match", "always"]
    instructions: str
    tools: list[SkillToolRef]
    knowledge_bases: list[str]
    guardrails: list[str]
    resources: list[SkillResource]
    # What the agent says when one of the skill's guardrails refuses; absent uses the platform's sentence.
    refusal: str | None = None
    # Absent on a skill that takes no inputs.
    inputs: list[SkillInputField] = Field(default_factory=list[SkillInputField])
    # Absent on a skill without parts: the whole body is one skill.
    parts: list[SkillPart] = Field(default_factory=list[SkillPart])
    # A skill that runs step by step; all absent on a skill without steps. Each step's check says who judges it
    # (`by`: a rule run on the step's result, or the model), set when the skill is saved.
    not_when: str = ""
    # The skill as written in the text editor; absent on a skill saved as a list of steps.
    source: str | None = None
    steps: list[SkillStepOut] = Field(default_factory=list[SkillStepOut])
    exit: dict[str, str] = Field(default_factory=dict[str, str])
    returns: list[ReturnFieldOut] = Field(default_factory=list[ReturnFieldOut])
    success: list[str] = Field(default_factory=list[str])


class Skill(Out):
    id: str
    name: str
    slug: str
    use_when: str
    loading: Literal["on_match", "always"]
    # The owning team's id; its name is filled on the list and detail reads (None when it cannot be read).
    owner_team: str
    owner_team_name: str | None = None
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
    # The described version's inputs and parts (the published one under view=published), so a list page carries what
    # an MCP prompt asks for without a read per skill.
    inputs: list[SkillInputField] = Field(default_factory=list[SkillInputField])
    parts: list[SkillPartSummary] = Field(default_factory=list[SkillPartSummary])
    # With usableBy=agent and agentId: the skill needs a tool or knowledge base the agent lacks, named in `needs`, so
    # the / menu shows it locked.
    locked: bool | None = None
    needs: list[str] | None = None


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
    # Who made it live. Who asked for the publish, and who approved it: approved_by is null when the team's publish
    # policy let it go live without a review; both are null for a version no request published.
    published_by: str | None = None
    requested_by: str | None = None
    approved_by: str | None = None
    # Always null today: nothing records a test run on a version.
    test_run: None


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


class ReferenceItem(Out):
    """One thing a brief or a step can mention with @."""

    kind: Literal["tool", "knowledge", "skill", "agent", "workflow"]
    id: str
    label: str
    hint: str | None = None
    # For an agent: whether it holds this already. For a skill: whether the skill names this tool or knowledge
    # base; None for a kind a skill does not hold.
    held: bool | None = None
    # What inserting it grants, in words ("Adds Dispute status lookup to this agent"); None when nothing is added.
    adds: str | None = None
    needs_approval: bool = False
    # Why it cannot be inserted, when it cannot.
    disabled: str | None = None


class ReferenceGroup(Out):
    kind: Literal["tool", "knowledge", "skill", "agent", "workflow"]
    label: str
    items: list[ReferenceItem]
    # Passed back as `cursor` with this group's `kind` for the next items; None when there are no more.
    next_cursor: str | None = None


class ReferenceSearch(Out):
    """Only kinds the caller may view, and only groups that have an item."""

    groups: list[ReferenceGroup]


class Blocker(Out):
    """One reason a publish is refused, in the one shape the agent, skill and workflow publish checks return: the
    workflow step (`node`) or the field it is in, its level and code, and the sentence the publish dialog shows."""

    node: str | None = None
    field: str | None = None
    level: Literal["error", "warning"] = "error"
    code: str
    message: str


class BlockerPosition(Out):
    """Where a publish problem is: the field (`steps`, `notWhen`, `useWhen`, `brief.never`, `source`), and the step
    (from 1) or list index when it has one; for `source`, `index` is the line (from 1)."""

    field: str
    step: int | None = None
    index: int | None = None


class PublishBlocker(Out):
    """One thing that blocks a publish. `id` names the reference for a reference problem, as `<kind>:<id>`."""

    kind: Literal[
        "missing_field",
        "missing_reference",
        "unavailable_reference",
        "bad_step",
        "bad_check",
        "bad_exit",
        "sub_skill_not_held",
        "prompt_rule_in_text",
        "review_open",
        "already_published",
        "deprecated",
        "too_long",
        # Only ever a warning: a tool a step's sentence names and the step does not run.
        "mention",
        "hint",
        # The agent's evals (api/eval_gate.py): a blocking step failed, the team requires a run and there is none or
        # no saved cases, or the team's evalsRequired setting could not be read.
        "eval_failed",
        "eval_not_run",
        "eval_no_cases",
        "eval_setting_unread",
    ]
    id: str | None = None
    position: BlockerPosition | None = None
    message: str
    # An eval problem's steps, as the Evals page shows them.
    details: EvalGateDetails | None = None


class BriefDraft(Out):
    """A proposed text per brief heading, drafted from a description. Nothing is saved: each heading is accepted or
    skipped in the console, and an accepted one saves as an ordinary edit of the brief."""

    job: str
    how_to_answer: str
    hand_off: list[str]
    examples: str
    never: list[str]


class AgentPrompt(Out):
    """The prompt one version of an agent gives the model, read only: its instructions, then the never rules last."""

    version: int
    text: str


class AgentPublishCheck(Out):
    """Whether the newest draft can be published, and each thing that stops it with the field it is in."""

    can_request: bool
    problems: list[PublishBlocker] = Field(default_factory=list[PublishBlocker])
    # The problems in the shape every publish check returns.
    blockers: list[Blocker] = Field(default_factory=list[Blocker])


class ReferenceAdded(Out):
    """What an insert granted the agent: the reference and anything it brought with it (a skill's tools, knowledge
    bases and the skills its steps run). Empty when the agent already held it; `agent_version` is then unchanged."""

    added: list[ReferenceItem]
    agent_version: int


class SkillPublishCheck(Out):
    can_request: bool
    # The problems in the shape every publish check returns.
    blockers: list[Blocker]
    problems: list[PublishBlocker] = Field(default_factory=list[PublishBlocker])
    # What does not block: a tool a step's sentence names and the step does not run.
    warnings: list[PublishBlocker] = Field(default_factory=list[PublishBlocker])
    edit_class: Literal["free", "re_test", "re_approval"]
    approvers_needed: int


class SkillLoadsDay(Out):
    date: str
    # Loads per agent name.
    counts: dict[str, int]
    total: int


class SkillTrace(Out):
    id: str
    at: str
    agent_name: str
    version: int
    input: str
    outcome: Literal["completed", "handed_off", "failed"]
    tool_calls: list[str]
    took_ms: int


class SkillActivity(Out):
    agents: list[str]
    # 14 days, oldest first.
    loads_per_day: list[SkillLoadsDay]
    loads30d: int = Field(alias="loads30d")
    # Loaded turns that completed without a hand-off or failure, 0 to 1.
    success_rate: float | None
    samples: list[SkillTrace]


class SkillCitation(Out):
    id: str
    kind: Literal["document", "case", "run", "chat", "template", "description"]
    label: str
    detail: str | None = None
    href: str | None = None
    section: str


class SkillProvenance(Out):
    origin: str
    detail: str
    citations: list[SkillCitation]


class SkillPendingReview(Out):
    id: str
    version: int
    edit_class: Literal["free", "re_test", "re_approval"]
    approvals: int
    needed: int


class SkillDetail(Skill):
    content: SkillContent
    # The text the editor shows: `content.source`, or a skill's stored steps written as text by the same reader.
    text: str
    # With `version`, the copy a draft save names as its base (`baseVersion`, `baseDigest`).
    digest: str
    versions: list[SkillVersion]
    # Both are empty today: skill tests moved into assurance suites and nothing sends a shape here.
    tests: list[JsonValue]
    runs: list[JsonValue]
    usage: list[SkillUsage]
    activity: SkillActivity
    provenance: SkillProvenance
    pending_review: SkillPendingReview | None = None
    publish_check: SkillPublishCheck


class SkillRendered(Out):
    """POST /v1/skills/{id}/render: the published version's text with the inputs filled in."""

    skill_id: str
    name: str
    slug: str
    version: int
    part: str | None = None
    part_name: str | None = None
    text: str


class SkillList(ListResult[Skill]):
    view_counts: dict[str, int]
    # The name of each owner team `facets.ownerTeam` counts, by its id, so the Owner team filter reads names.
    team_names: dict[str, str] = Field(default_factory=dict[str, str])


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


class TeamChoice(Out):
    id: str
    # None when platform-service cannot name the team; the console shows the id.
    name: str | None


class SkillOptions(Out):
    # The ids of `owner_teams`, kept for callers that read the earlier shape.
    teams: list[str]
    # The teams the caller may create skills in, each with its name: what New skill's Owner team offers.
    owner_teams: list[TeamChoice]
    tools: list[SkillToolRef]
    knowledge_bases: list[str]
    limits: dict[str, int]


class SkillTextNote(Out):
    line: int
    message: str


class SkillTextError(SkillTextNote):
    # The mention, as `<kind>:<id>`.
    id: str


class SkillTextUses(Out):
    tools: int
    knowledge: int
    skills: int
    agents: int
    workflows: int


class SkillTextKeyword(Out):
    """The keyword a line is written with (`if`, `else` for else or otherwise, `stop`) and where it sits in the line
    after its indent, past any list marker. Set whether or not the line reads as one: the editor highlights it only on
    a line whose kind is that keyword, and indents after an `if` or `else` it is typing."""

    word: Literal["if", "else", "stop"]
    start: int
    end: int


class SkillTextLine(Out):
    """One line of the text: its kind, the step (from 1) it is part of, how its condition is decided (an `if`
    line: `checked` on the tool's result, or `agent`, decided from the conversation) and the tool its line runs."""

    line: int
    kind: Literal["text", "step", "if", "else", "stop", "blank"]
    step: int | None = None
    how: Literal["checked", "agent"] | None = None
    tool: str | None = None
    # How many path levels in the line is, as the reader counts its indent (the editor draws its guides from it).
    depth: int = 0
    keyword: SkillTextKeyword | None = None


class SkillTextReading(Out):
    """POST /v1/skills/{id}/text: how a skill's text reads, as a save will read it. Hints never block anything;
    `errors` (a mention of something that no longer exists) block a publish, never a save."""

    hints: list[SkillTextNote]
    errors: list[SkillTextError]
    uses: SkillTextUses
    lines: list[SkillTextLine]
    # What the editor offers after `if ` for each mentioned tool (`@tool:<id>`), from what it returns.
    phrases: dict[str, list[str]]
    steps: int
    # The line each step starts on, by step.
    step_lines: list[int]
