"""Kernel inputs and outputs (spec 15 sections 2 and 5), trimmed to what chat needs in phase 1.

Fields from spec 15 that need services the Runtime does not have yet (run context token, skills, memory, ledger
replay, trace context) are left out rather than stubbed; each lands with its service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# `workflow`: the tool starts a published workflow, whose own review steps are the gate (workflows-as-tools.md).
Access = Literal["read", "write", "workflow"]


@dataclass(frozen=True)
class PromptFragment:
    text: str
    # Stable fragments sit first in the system prompt so the provider's prefix cache covers them (spec 15 3.1).
    stable: bool = True


@dataclass(frozen=True)
class AgentSettings:
    agent_id: str
    version: int
    instructions: list[PromptFragment]
    model_alias: str
    max_tool_calls: int = 6
    max_steps: int = 8


@dataclass(frozen=True)
class ToolGrant:
    name: str
    server: str
    description: str
    access: Access
    input_schema: dict[str, Any]

    @property
    def gated(self) -> bool:
        return self.access not in ("read", "workflow")


@dataclass(frozen=True)
class Passage:
    document_id: str
    title: str
    section: str
    version: str
    text: str
    kb_id: str


@dataclass(frozen=True)
class TranscriptMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class PendingCall:
    tool_call_id: str
    key: str
    action_id: str
    tool: str
    server: str
    access: Access
    input: dict[str, Any]
    input_hash: str


@dataclass(frozen=True)
class Interrupt:
    interrupt_id: str
    kind: Literal["approval"]
    needed: str
    pending_call: PendingCall
    # The loop library's message history up to the pause, opaque outside the kernel; the resumed turn continues it.
    history: bytes


@dataclass(frozen=True)
class Resume:
    interrupt: Interrupt
    decision: Literal["approved", "rejected"]
    reason: str | None = None
    approval_token: str | None = None


@dataclass(frozen=True)
class TurnRequest:
    turn_id: str
    run_id: str
    settings: AgentSettings
    tools: list[ToolGrant]
    transcript: list[TranscriptMessage] = field(default_factory=list[TranscriptMessage])
    user_turn: str | None = None
    kb_ids: list[str] = field(default_factory=list[str])
    variables: dict[str, str] = field(default_factory=dict[str, str])
    resume: Resume | None = None
    deadline_seconds: float = 120.0


@dataclass
class ToolCallRecord:
    tool_call_id: str
    key: str
    tool: str
    server: str
    access: Access
    input: dict[str, Any]
    input_hash: str
    status: Literal["running", "ok", "error", "gated"]
    output: Any = None
    duration_ms: int = 0
    view: dict[str, Any] | None = None


@dataclass(frozen=True)
class CitationRef:
    n: int
    passage: Passage


@dataclass(frozen=True)
class TokenUsage:
    """Tokens and provider requests one turn used. Zero when the turn failed before the model answered: a failed
    provider call is not reported back with its usage."""

    input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0


@dataclass
class TurnResult:
    turn_id: str
    status: Literal["completed", "interrupted", "failed"]
    stop_reason: Literal["final", "interrupt", "max_tool_calls", "deadline", "error"]
    text: str
    tool_calls: list[ToolCallRecord]
    citations: list[CitationRef]
    no_answer: bool = False
    interrupt: Interrupt | None = None
    error: str | None = None
    # Set when the model endpoint refused the call (models-service's rate limit, budget, clearance or alias): its
    # HTTP status and code, so the caller answers with the same refusal instead of a generic failure.
    error_status: int | None = None
    error_code: str | None = None
    # The model that produced the final response; differs from the alias when a fallback answered.
    model_name: str | None = None
    context_digest: dict[str, str] = field(default_factory=dict[str, str])
    usage: TokenUsage = field(default_factory=TokenUsage)
