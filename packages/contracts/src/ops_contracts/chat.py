"""Chat contract, mirroring apps/console/src/lib/types/chat.ts field for field.

Hand-written until `make contracts` generates it from packages/contracts (spec 17 section 4). Fields are snake_case in
Python and camelCase on the wire; every model dumps with `wire()` so the console reads exactly the TypeScript shape.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
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


class ToolGate(WireModel):
    gate: str
    reviewers: str


class ToolCall(WireModel):
    id: str
    name: str
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
    feedback: MessageFeedback | None = None
    no_answer: bool | None = None
    # Which model answered, e.g. a fallback when the primary provider refused (not yet in chat.ts).
    model: str | None = None
    stopped: bool | None = None
    error: str | None = None
    # Why, when the model endpoint refused the reply (rate_limited, key_budget_exhausted, ...); kept with the message
    # so a reload shows the same plain text the live stream did.
    error_code: str | None = None


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


class ChatThread(ChatThreadBase):
    messages: list[ChatMessage]


class ChatThreadRow(ChatThreadBase):
    preview: str
    widgets: int
    citations: int


class ChatThreadInput(WireModel):
    agent_id: str
    kb_ids: list[str]
    title: str | None = None


class ChatThreadPatch(WireModel):
    title: str | None = None
    pinned: bool | None = None
    archived: bool | None = None
    kb_ids: list[str] | None = None


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


# ── Stream events ──

StatusPhase = Literal["thinking", "retrieving", "calling_tool", "writing"]


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


class TextEvent(WireModel):
    type: Literal["text"] = "text"
    delta: str


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
    | TextEvent
    | CitationsEvent
    | DoneEvent
    | ErrorEvent
)
