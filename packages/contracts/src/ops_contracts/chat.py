"""Chat contract, mirroring apps/console/src/lib/types/chat.ts field for field.

Hand-written until `make contracts` generates it from packages/contracts (spec 17 section 4). Fields are snake_case in
Python and camelCase on the wire; every model dumps with `wire()` so the console reads exactly the TypeScript shape.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class WireModel(BaseModel):
    """camelCase on the wire, snake_case in Python, unknown fields refused so a renamed console field fails loudly."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    def wire(self) -> dict[str, Any]:
        """The JSON the console reads: aliases, and optional fields left out rather than sent as null."""
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


class Citation(WireModel):
    n: int
    document_id: str
    title: str
    section: str
    page: int | None = None
    version: str
    snippet: str
    url: str | None = None
    precedence_note: str | None = None
    stale: bool | None = None
    connection_revoked: bool | None = None
    in_force_on: str | None = None
    superseded_today: bool | None = None


class KbRef(WireModel):
    id: str
    name: str


class ChatAgent(WireModel):
    id: str
    name: str
    role: str
    version: int
    model: str
    default_kb_ids: list[str]
    suggestions: list[str]
    # Knowledge bases this agent may search, with display names; a thread may narrow these, never widen (07 CD-8).
    kbs: list[KbRef] | None = None


# ── Widgets ──


class WidgetBase(WireModel):
    id: str
    title: str
    app: str
    tool: str
    as_of: str
    # The tool's action in words, as people read it (c-508); `tool` stays for builders and the event log.
    tool_label: str = ""


class TableColumn(WireModel):
    key: str
    label: str
    align: Literal["left", "right"] | None = None
    tone: bool | None = None


class TableWidget(WidgetBase):
    kind: Literal["table"] = "table"
    columns: list[TableColumn]
    rows: list[dict[str, str | int | float]]
    href: str | None = None


class ChartSeries(WireModel):
    key: str
    label: str


class ChartWidget(WidgetBase):
    kind: Literal["chart"] = "chart"
    chart: Literal["bar", "line"]
    x_key: str
    y_label: str | None = None
    series: list[ChartSeries]
    data: list[dict[str, str | int | float]]


class LabelValue(WireModel):
    label: str
    value: str


class RecordWidget(WidgetBase):
    kind: Literal["record"] = "record"
    subtitle: str | None = None
    status: str | None = None
    fields: list[LabelValue]
    href: str | None = None


ApprovalState = Literal["pending", "awaiting_second", "approved", "rejected"]
Risk = Literal["critical", "high", "medium", "low"]


class ApprovalWidget(WidgetBase):
    kind: Literal["approval"] = "approval"
    review_id: str
    action: str
    summary: str
    fields: list[LabelValue]
    risk: Risk
    consequence: str | None = None
    # The operation needs two approvers, so the console asks for a step-up before sending the approval.
    step_up: bool | None = None
    state: ApprovalState
    decided_by: str | None = None
    reason: str | None = None
    # Whom the thread waits on while the approval is open: the operation's reviewers, or a second approver.
    waiting_on: str | None = None
    # Whether the person reading the thread may decide it now, by the decision route's checks (c-123).
    can_decide: bool | None = None


class FormWidgetField(WireModel):
    key: str
    label: str
    type: Literal["text", "select", "textarea"]
    options: list[str] | None = None
    value: str | None = None
    required: bool | None = None


class FormWidget(WidgetBase):
    kind: Literal["form"] = "form"
    description: str
    fields: list[FormWidgetField]
    submit_label: str
    state: Literal["open", "submitted"]
    values: dict[str, str] | None = None
    result: str | None = None


class Metric(WireModel):
    label: str
    value: str
    delta: str | None = None
    tone: Literal["good", "bad", "neutral"] | None = None


class MetricWidget(WidgetBase):
    kind: Literal["metric"] = "metric"
    metrics: list[Metric]


ChatWidget = Annotated[
    TableWidget | ChartWidget | RecordWidget | ApprovalWidget | FormWidget | MetricWidget,
    Field(discriminator="kind"),
]


class ApproveAction(WireModel):
    type: Literal["approve"]
    step_up_token: str | None = None


class RejectAction(WireModel):
    type: Literal["reject"]
    reason: str


class SubmitAction(WireModel):
    type: Literal["submit"]
    values: dict[str, str]


WidgetAction = Annotated[ApproveAction | RejectAction | SubmitAction, Field(discriminator="type")]

# ── Messages ──


class WidgetHint(WireModel):
    # A renderer id the console uses when it can draw the shape (table, line, bar, area, fields, stat, ...).
    prefer: str | None = None
    title: str | None = None
    x: str | None = None
    y: list[str] | None = None
    # Rows the tool returned when the part holds fewer (the shaper keeps MAX_ROWS), so the console can say so.
    truncated_from: int | None = None


class WidgetTemplateRef(WireModel):
    """The published widget template a layout part was filled from (c-082)."""

    id: str
    version: int
    name: str


class WidgetPart(WireModel):
    """A shaped result (c-055, "Widget architecture"): a shape and its data, never a tool or component name; the
    console's widget registry picks how to draw it. Matches apps/console/src/lib/types/widgets.ts.

    Or a layout (c-082): a tree of catalogue primitives the kernel checked (ops_agent_kernel.layout), filled from an
    agent's widget template (`template` names it) or composed by the model. Exactly one of `shape` and `layout`."""

    type: Literal["widget"] = "widget"
    id: str
    shape: Literal["rows", "series", "record", "metric", "form", "decision", "steps"] | None = None
    data: Any = None
    hint: WidgetHint | None = None
    # JSON Schema for a `form` part's fields (lib/types/widgets.ts).
    schema_: Any | None = Field(default=None, alias="schema")
    layout: dict[str, Any] | None = None
    template: WidgetTemplateRef | None = None
    # The generic kind the layout is (c-176, ops_agent_kernel.kinds) when the agent showed one with `present {kind}`.
    kind: str | None = None

    @model_validator(mode="after")
    def _one_form(self) -> WidgetPart:
        if (self.shape is None) == (self.layout is None):
            raise ValueError("a widget part has exactly one of shape and layout")
        return self


class ToolGate(WireModel):
    gate: str
    reviewers: str


class ToolCall(WireModel):
    id: str
    name: str
    # The call's action in words ("Look up accounts"), as review_text.call_label words it; people read this, not `name`.
    label: str | None = None
    server: str
    input: dict[str, Any]
    output: Any = None
    status: Literal["running", "success", "failed"]
    duration_ms: int
    gated: ToolGate | None = None


class MessageFeedback(WireModel):
    rating: Literal["up", "down"]
    reason: str | None = None


class ChatAttachment(WireModel):
    file_id: str
    name: str
    size: int


class LoadedSkill(WireModel):
    skill_id: str
    name: str
    version: int
    # The words that matched its use-when line; "Always on" for always-on skills.
    matched: str


class BudgetPause(WireModel):
    """A turn paused on the conversation's budget (c-103). The numbers are the thread's ledger at the pause, from
    agents-service's meter, never a sum the client made."""

    # The pause's interrupt id; an answer names it, so a tab showing an older pause is refused.
    id: str | None = None
    # Which cap was reached: calls, tokens or cost.
    limit: Literal["calls", "tokens", "cost"]
    spent: str
    cap: str
    state: Literal["waiting", "continued", "raised"] = "waiting"
    # Who continued or raised it, and the caps it went on with.
    answered_by: str | None = None
    new_cap: str | None = None


class BudgetAnswer(WireModel):
    """Continue adds one more allotment of what the conversation started with (its owner); raise sets new caps for
    this conversation (an admin of its team)."""

    action: Literal["continue", "raise"]
    # The pause this answers (BudgetPause.id); when given and the conversation now waits on another, 409 stale_pause.
    pause_id: str | None = None
    max_calls: int | None = Field(default=None, ge=1)
    max_cost: Decimal | None = Field(default=None, gt=0)


class GuardrailHit(WireModel):
    guardrail_id: str
    version: int
    name: str
    topic: str
    # before: refused unanswered; after: the answer was replaced by the message; corrected: rewritten once without it.
    when: Literal["before", "after", "corrected"]


class GuardrailAudit(WireModel):
    """Text a guardrail kept from the person (withheld: never shown) or took back after it was shown (retracted),
    with the rule and when. Only a reader allowed to view the audit gets it; the stream never carries it."""

    kind: Literal["withheld", "retracted"]
    text: str
    guardrail: GuardrailHit | None = None
    stop_reason: str | None = None
    at: str | None = None


class ChatOverrides(WireModel):
    """What a caller asks for on a thread or one message, checked against the agent's limits by the resolver
    (agents-service activities/overrides.py); unknown fields are refused."""

    model: str | None = None
    temperature: float | None = None
    # Added after the agent's instructions; never replaces them.
    instructions: str | None = None
    # Granted tools switched off; a caller never adds one.
    tools_off: list[str] | None = None
    knowledge_base_ids: list[str] | None = None
    budget_usd: float | None = None
    output_schema: dict[str, Any] | None = None
    variables: dict[str, Any] | None = None
    # Widgets narrow only: switch pinned ones off, switch composing off, lower the per-answer cap.
    widgets_off: list[str] | None = None
    compose_off: bool | None = None
    widgets_per_turn: int | None = None


class ReplyUsage(WireModel):
    """What one reply spent (c-286): its model calls, tokens and cost from the model call records, and the seconds from
    its run starting to finishing."""

    calls: int
    input_tokens: int
    output_tokens: int
    # Two decimal places of the workspace currency, as a string so no float rounds it.
    cost: str
    seconds: float | None = None


class EffectiveSettings(WireModel):
    """The settings a turn ran on and where each came from ("agent", "thread" or "turn"); recorded on every turn as
    `run.settings` and kept with the assistant message."""

    model: str
    temperature: float | None = None
    added_instructions: list[str] = Field(default_factory=list[str])
    tools_off: list[str] = Field(default_factory=list[str])
    knowledge_base_ids: list[str]
    budget_usd: float | None = None
    output_schema: dict[str, Any] | None = None
    variables: dict[str, Any] | None = None
    widgets_off: list[str] = Field(default_factory=list[str])
    compose_off: bool = False
    widgets_per_turn: int | None = None
    sources: dict[str, str] = Field(default_factory=dict[str, str])


class NamedRef(WireModel):
    id: str
    name: str


class ThreadLimits(WireModel):
    """What the agent lets a banker change on this thread, joined with names, so the settings panel offers only what
    the server would accept."""

    allowed_models: list[str]
    default_model: str
    temperature_min: float | None = None
    temperature_max: float | None = None
    knowledge_bases: list[NamedRef]
    switchable_tools: list[NamedRef]
    may_add_instructions: bool
    budget_ceiling_usd: float | None = None
    switchable_widgets: list[NamedRef] = Field(default_factory=list[NamedRef])
    may_compose: bool = False
    widgets_per_turn: int | None = None


class ThreadSettings(WireModel):
    limits: ThreadLimits
    overrides: ChatOverrides | None = None
    effective: EffectiveSettings


class RememberedItem(WireModel):
    """One memory a reply saved about the person (c-206); an episode has no key."""

    id: str
    kind: Literal["fact", "preference", "episode"]
    key: str | None = None
    value: str


class ChatMessage(WireModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    at: str
    attachments: list[ChatAttachment] | None = None
    citations: list[Citation] | None = None
    # RetrievalTrace is owned by the knowledge service; the Runtime has no retrieval trace to send yet.
    trace: dict[str, Any] | None = None
    tool_calls: list[ToolCall] | None = None
    widgets: list[ChatWidget] | None = None
    # Shaped tool results, drawn by the console's widget registry; kept with the message so a reload shows them.
    parts: list[WidgetPart] | None = None
    feedback: MessageFeedback | None = None
    no_answer: bool | None = None
    # Which model answered, e.g. a fallback when the primary provider refused (not yet in chat.ts).
    model: str | None = None
    stopped: bool | None = None
    error: str | None = None
    # Why, when the model endpoint refused the reply (rate_limited, key_budget_exhausted, ...); kept with the message
    # so a reload shows the same plain text the live stream did.
    error_code: str | None = None
    # The pinned guardrail that refused the question or replaced the answer; the content is then its message.
    guardrail: GuardrailHit | None = None
    # What the guardrail kept back or took back, for an auditor only (GuardrailAudit).
    guardrail_audit: list[GuardrailAudit] | None = None
    # Skills the turn loaded, always-on first; the turn's detail reads "Loaded skill X v1".
    skills: list[LoadedSkill] | None = None
    # The settings the turn ran on (c-071); absent on turns from before overrides.
    settings: EffectiveSettings | None = None
    # What the reply spent (c-286); absent when no model call was recorded for it.
    usage: ReplyUsage | None = None
    # The conversation's budget ran out during this turn (c-103); the turn waits until it is continued or raised.
    budget: BudgetPause | None = None
    # The agent that wrote this reply (c-174): after a handover it is not the agent the conversation started on.
    agent_id: str | None = None
    agent_name: str | None = None
    # What this turn saved about the person (c-206), so the reply can say so; absent when it saved nothing.
    remembered: list[RememberedItem] | None = None


class ChatThreadBase(WireModel):
    id: str
    title: str
    agent_id: str
    agent_name: str
    agent_version: int
    kb_ids: list[str]
    kb_names: list[str]
    pinned: bool
    archived: bool
    owner: str
    created_at: str
    last_message_at: str
    message_count: int
    # Set while the conversation is handed over (c-174): the agent it started on, which Back returns to.
    start_agent_id: str | None = None
    start_agent_name: str | None = None
    # A builder's test of the agent (c-284), set by the server only: left out of counts and memory, listed under Test.
    test: bool = False


class ChatThread(ChatThreadBase):
    messages: list[ChatMessage]


class ChatThreadRow(ChatThreadBase):
    preview: str
    widgets: int
    citations: int


class ChatThreadInput(WireModel):
    # Left out, the conversation starts on the team's default agent (c-174).
    agent_id: str | None = None
    kb_ids: list[str]
    title: str | None = None
    # Apply to every message in the thread. Raw, so agents-service's overrides.parse refuses an unknown or mistyped
    # field with 422 naming it, like a value outside the limits.
    overrides: dict[str, Any] | None = None
    attachments: list[ChatAttachment] | None = None
    # Ask to test the agent (c-284): each message runs its newest version, draft included. Granted only to a caller
    # who may test the agent; the mark is stored by the server and never changes after.
    test: bool = False
    # With `test`, the saved version every message runs instead of the newest (c-286): a compare asks the same question
    # of two versions on two test threads.
    test_version: int | None = Field(default=None, ge=1)


class ChatThreadPatch(WireModel):
    title: str | None = None
    pinned: bool | None = None
    archived: bool | None = None
    kb_ids: list[str] | None = None
    # Hands the conversation to this agent (an @mention, c-174); the agent it started on hands it back.
    agent_id: str | None = None


class TeamDefaultAgent(WireModel):
    # None until provisioning or a team admin sets one.
    agent_id: str | None
    agent_name: str | None = None
    # Whether the caller may change it (chat.manage in their team), so the console offers the control only then.
    can_change: bool = False


class TeamDefaultAgentInput(WireModel):
    agent_id: str


class BulkThreadPatch(WireModel):
    pinned: bool | None = None
    archived: bool | None = None


class BulkUpdateInput(WireModel):
    ids: list[str]
    patch: BulkThreadPatch


class BulkDeleteInput(WireModel):
    ids: list[str]


class BulkSkip(WireModel):
    id: str
    reason: str


class BulkResult(WireModel):
    updated: list[str]
    skipped: list[BulkSkip]


class SendInput(WireModel):
    content: str
    attachments: list[ChatAttachment] | None = None
    # This message only; may narrow the thread's overrides. Raw, checked by overrides.parse (see ChatThreadInput).
    overrides: dict[str, Any] | None = None
    regenerate: str | None = None
    edit: str | None = None


class FeedbackInput(WireModel):
    feedback: MessageFeedback | None


class PaginationMeta(WireModel):
    page: int
    page_size: int
    total: int
    total_pages: int
    has_next: bool
    has_prev: bool


class ThreadList(WireModel):
    """`ListResult<ChatThreadRow>`: rows, pagination and per-key facet counts."""

    data: list[ChatThreadRow]
    pagination: PaginationMeta
    facets: dict[str, dict[str, int]]
    # Set when the list was read by `cursor` and more rows follow; pass it back as `cursor` for the next page.
    next_cursor: str | None = None


# ── Stream events ──

StatusPhase = Literal["thinking", "retrieving", "calling_tool", "writing", "checking"]


class StartEvent(WireModel):
    type: Literal["start"] = "start"
    user_message: ChatMessage | None = None
    message_id: str


class StatusEvent(WireModel):
    type: Literal["status"] = "status"
    phase: StatusPhase


class ToolStartEvent(WireModel):
    type: Literal["tool_start"] = "tool_start"
    call: ToolCall


class ToolEndEvent(WireModel):
    type: Literal["tool_end"] = "tool_end"
    call: ToolCall


class WidgetEvent(WireModel):
    type: Literal["widget"] = "widget"
    widget: ChatWidget


class PartEvent(WireModel):
    """A shaped tool result, after the tool_end it came from."""

    type: Literal["part"] = "part"
    part: WidgetPart


class TextEvent(WireModel):
    type: Literal["text"] = "text"
    delta: str


class ReplaceEvent(WireModel):
    """The answer streamed so far is replaced by `text`: a guarded answer its after-answer check corrected or refused,
    or cleared when the turn ended before the check ran. What was shown before it is kept on the record as a
    `retracted` GuardrailAudit, for a reader allowed to view the audit
    (docs/services/agents-service/chat-streaming.md)."""

    type: Literal["replace"] = "replace"
    text: str


class CitationsEvent(WireModel):
    type: Literal["citations"] = "citations"
    citations: list[Citation]


class DoneEvent(WireModel):
    type: Literal["done"] = "done"
    message: ChatMessage


class ErrorEvent(WireModel):
    type: Literal["error"] = "error"
    message: str
    partial: ChatMessage
    # Why, when the model endpoint refused the call: rate_limited, key_budget_exhausted, sensitivity_not_cleared.
    code: str | None = None


ChatStreamEvent = (
    StartEvent
    | StatusEvent
    | ToolStartEvent
    | ToolEndEvent
    | WidgetEvent
    | PartEvent
    | TextEvent
    | ReplaceEvent
    | CitationsEvent
    | DoneEvent
    | ErrorEvent
)
