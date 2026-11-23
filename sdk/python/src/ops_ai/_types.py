"""Public TypedDict models builders import from `ops_ai`.

Most names are re-exports of the generated OpenAPI TypedDicts. Chat `/v1/chat/*` is not in the agents OpenAPI
document, so its thread and stream shapes are hand-written here (camelCase on the wire). `AgentChatReply` and
`WaitedRun` are SDK shapes (`agents.chat` / `runs.wait`), not API DTOs.
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired

from typing_extensions import TypedDict

from ._generated.agents.models import (
    Agent,
    CasePage,
    CaseRow,
    CaseTypeDetail,
    CaseTypeView,
    CaseView,
    DefinitionPublished,
    DefinitionRow,
    DefinitionView,
    FormView,
    Guardrail,
    InboxItem,
    PublishReview,
    RunDetail,
    RunRow,
    RunStarted,
    Skill,
    SkillCreateInput,
    SkillDetail,
    TaskTypeDetail,
    TaskTypeView,
    ThreadCreated,
    ThreadReview,
    ThreadState,
    ThreadView,
    WidgetTemplateOut,
    WorkflowDetail,
)
from ._generated.files.models import FileDetail, FileRow
from ._generated.kb.models import KnowledgeBase, KnowledgeBaseDetail, KnowledgeBaseRow, SearchOut
from ._generated.platform.models import TeamOut
from ._generated.tools.models import ToolModule, ToolModuleDetail

# A task list row is either a human-in-the-loop review or a publish review.
TaskItem = ThreadReview | PublishReview


class AgentChatReply(TypedDict):
    """Collected reply from `agents.chat` or wait-mode `agents.run`."""

    threadId: str
    reply: str
    text: str
    events: list[Any]
    citations: list[Any]
    toolCalls: list[Any]
    runId: NotRequired[str]
    mode: NotRequired[str]
    chunks: NotRequired[list[Any]]


class AgentBackgroundRun(TypedDict):
    """Handle returned when `agents.run(..., mode="background")` starts a drain in another thread."""

    threadId: str
    runId: str
    mode: Literal["background"]


class WaitedRun(TypedDict):
    """A run after `runs.wait`, with `taskId` when it stopped on a human task."""

    id: str
    status: str
    workflowId: str
    digest: str
    createdAt: str
    createdBy: str
    error: str | None
    finishedAt: str | None
    input: dict[str, Any] | None
    mode: str
    outcome: str | None
    output: Any
    updatedAt: str
    version: int
    waiting: Any
    taskId: NotRequired[str]
    canCancel: NotRequired[bool | None]
    canRetry: NotRequired[bool | None]
    outcomeText: NotRequired[str | None]
    workflowName: NotRequired[str | None]
    result: NotRequired[Any]
    steps: NotRequired[list[Any]]


class ChatThread(TypedDict):
    """A `/v1/chat/threads` conversation as the chat screen reads it (camelCase on the wire)."""

    id: str
    title: NotRequired[str]
    agentId: NotRequired[str]
    agentName: NotRequired[str]
    agentVersion: NotRequired[int]
    kbIds: NotRequired[list[str]]
    kbNames: NotRequired[list[str]]
    pinned: NotRequired[bool]
    archived: NotRequired[bool]
    owner: NotRequired[str]
    createdAt: NotRequired[str]
    lastMessageAt: NotRequired[str]
    messageCount: NotRequired[int]
    messages: NotRequired[list[dict[str, Any]]]
    startAgentId: NotRequired[str | None]
    startAgentName: NotRequired[str | None]
    test: NotRequired[bool]
    readable: NotRequired[bool]
    teamId: NotRequired[str]
    teamName: NotRequired[str]


class ChatEvent(TypedDict, total=False):
    """One server-sent event from `chat.say` (the event's `data` object)."""

    type: str
    message: dict[str, Any]
    messageId: str
    userMessage: dict[str, Any]
    phase: str
    call: dict[str, Any]
    widget: dict[str, Any]
    part: dict[str, Any]
    delta: str
    text: str
    citations: list[Any]
    partial: dict[str, Any]
    code: str


__all__ = [
    "Agent",
    "AgentBackgroundRun",
    "AgentChatReply",
    "CasePage",
    "CaseRow",
    "CaseTypeDetail",
    "CaseTypeView",
    "CaseView",
    "ChatEvent",
    "ChatThread",
    "DefinitionPublished",
    "DefinitionRow",
    "DefinitionView",
    "FileDetail",
    "FileRow",
    "FormView",
    "Guardrail",
    "InboxItem",
    "KnowledgeBase",
    "KnowledgeBaseDetail",
    "KnowledgeBaseRow",
    "PublishReview",
    "RunDetail",
    "RunRow",
    "RunStarted",
    "SearchOut",
    "Skill",
    "SkillCreateInput",
    "SkillDetail",
    "TaskItem",
    "TaskTypeDetail",
    "TaskTypeView",
    "TeamOut",
    "ThreadCreated",
    "ThreadReview",
    "ThreadState",
    "ThreadView",
    "ToolModule",
    "ToolModuleDetail",
    "WaitedRun",
    "WidgetTemplateOut",
    "WorkflowDetail",
]
