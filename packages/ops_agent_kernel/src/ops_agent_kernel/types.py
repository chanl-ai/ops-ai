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
class Guardrail:
    """A pinned guardrail version's rule (c-063): the topics the agent must not answer, and what it says instead."""

    guardrail_id: str
    version: int
    name: str
    topics: tuple[str, ...]
    message: str
    # (topic, scope) pairs: what a topic covers and what it does not, listed beside it for the classifier. A topic
    # without one is listed as its bare label.
    scopes: tuple[tuple[str, str], ...] = ()
    # Hold until checked: the answer is shown only after its after-answer check passes, for topics where even a moment
    # on screen is too much. Off, the answer streams as it is written and is replaced if the check then fails.
    hold: bool = False


@dataclass(frozen=True)
class Skill:
    """A pinned skill version (spec 11): on_match skills are indexed and loaded with load_skill, always skills are
    added to every turn after the instructions. `guardrails` are blocked-topic lines that apply while it is loaded."""

    skill_id: str
    version: int
    name: str
    slug: str
    use_when: str
    loading: Literal["on_match", "always"]
    instructions: str
    guardrails: tuple[str, ...] = ()
    tokens: int = 0
    # What the agent says when one of this skill's guardrails refuses (a next step, not just a no); empty uses the
    # platform's sentence.
    refusal: str = ""


@dataclass(frozen=True)
class WidgetTemplate:
    """A pinned widget template version (c-082): a tree of catalogue primitives with `$bind` pointers into data that
    must match `schema`. `use_when` is the line the present tool's description gives the model."""

    widget_id: str
    version: int
    name: str
    use_when: str
    tree: dict[str, Any]
    schema: dict[str, Any]


@dataclass(frozen=True)
class AgentSettings:
    agent_id: str
    version: int
    instructions: list[PromptFragment]
    model_alias: str
    # None: no cap. A real agent may need many; seeds and tests set low ones.
    max_tool_calls: int | None = 6
    # Model requests in one turn (the loop's steps). Always a number: an uncapped loop would spend real calls until
    # the deadline, so an agent with no cap set runs on the platform default.
    max_steps: int = 8
    # A caller's temperature within the agent's limits (c-071); None leaves the model's default.
    temperature: float | None = None
    # Checked before and after the answer by a classification call; none means today's path, no extra call.
    guardrails: list[Guardrail] = field(default_factory=list[Guardrail])
    # Pinned guardrails the builder switched off: never checked (no classification call), named on the turn's result
    # so a turn never looks protected by them.
    guardrails_off: list[Guardrail] = field(default_factory=list[Guardrail])
    skills: list[Skill] = field(default_factory=list[Skill])
    # Widgets the agent may fill (c-082), whether it may compose layouts from the catalogue, and how many widgets one
    # turn may show (None: no cap; the agent's own setting is the only limit).
    widgets: list[WidgetTemplate] = field(default_factory=list[WidgetTemplate])
    compose: bool = False
    widgets_per_turn: int | None = None
    # Mask personal data in what the turn shows and returns (the agent's redactPii, c-293); the model sees it all.
    redact_pii: bool = False


@dataclass(frozen=True)
class ToolGrant:
    name: str
    server: str
    description: str
    access: Access
    input_schema: dict[str, Any]
    # Whether a write waits for a person's approval: the gateway registry's flag for the operation, raised by the team's
    # toolWritesNeedApproval policy. Required unless the registry says otherwise, so a grant built without it pauses.
    requires_approval: bool = True

    @property
    def gated(self) -> bool:
        return self.access not in ("read", "workflow") and self.requires_approval


@dataclass(frozen=True)
class Passage:
    document_id: str
    title: str
    section: str
    version: str
    text: str
    kb_id: str
    # The page the passage starts on, when the source has pages (a PDF); cited with the section.
    page: int | None = None


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
    # On-match skills loaded before the pause ({skillId, version, name, matched}): the resumed turn keeps them loaded,
    # so their guardrails still check the answer and the per-turn caps go on from where they were.
    loaded_skills: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])


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
    # What knowledge search uses when it is not the whole user turn (a workflow agent step searches the prompt,
    # not the mapped input JSON whose names and ids drown the handbook terms).
    search_text: str | None = None
    kb_ids: list[str] = field(default_factory=list[str])
    # The conversation named knowledge bases and the agent no longer holds any of them: the turn says so and does not
    # call the model, which would otherwise answer from its own knowledge, uncited.
    knowledge_withdrawn: bool = False
    # Whether the person asked this turn for knowledge (the conversation named knowledge bases), so finding none is a
    # no-answer. None: whenever `kb_ids` is set, as a workflow's knowledge step asks.
    knowledge_asked: bool | None = None
    variables: dict[str, str] = field(default_factory=dict[str, str])
    resume: Resume | None = None
    deadline_seconds: float = 120.0
    # A JSON Schema the turn's answer must match (a workflow's agent step): the model returns structured output
    # through the call, validated against it, on `TurnResult.output`; a mismatch finishes with `schema_error`.
    output_schema: dict[str, Any] | None = None


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
    stop_reason: Literal[
        "final",
        "interrupt",
        "max_tool_calls",
        "max_steps",
        "deadline",
        "error",
        "schema_error",
        # A turn asked for structured output ended without it (kernel.finish): the step's error port, with the reason.
        "no_output",
        "guardrail",
        "guardrail_unavailable",
    ]
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
    # The validated structured answer when the request named an output schema; None otherwise.
    output: Any = None
    # The guardrail that refused, replaced or corrected the answer: {guardrailId, version, name, topic, when}, when one
    # of before (refused unanswered), after (replaced by its message) or corrected (rewritten once without the topic).
    guardrail: dict[str, Any] | None = None
    # Text a guardrail kept from the person (a withdrawn or rewritten answer, or the unchecked part of a guarded
    # turn that ended early). For the run's audit record only; never shown in the conversation.
    withheld: str | None = None
    # Text the person saw as it streamed and a guardrail then replaced (a refused or rewritten answer, or the unchecked
    # part of a turn that ended early). Distinct from `withheld`, which was never shown. Audit record only.
    retracted: str | None = None
    # Skills this turn loaded, always-on ones first: {skillId, name, version, matched}.
    skills: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    # The guardrails this turn checked and the pinned ones switched off: {guardrailId, version, name} each.
    guardrails_checked: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    guardrails_off: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
