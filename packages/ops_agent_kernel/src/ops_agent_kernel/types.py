"""Kernel inputs and outputs (spec 15 sections 2 and 5), trimmed to what chat needs in phase 1.

Fields from spec 15 that need services the Runtime does not have yet (run context token, skills, memory, ledger
replay, trace context) are left out rather than stubbed; each lands with its service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, NotRequired, TypedDict

from ops_contracts.skill_run import SkillProgram, SkillRunState
from ops_service_kit.http import Json

# `workflow`: the tool starts a published workflow, whose own review steps are the gate (workflows-as-tools.md).
Access = Literal["read", "write", "workflow"]
LoopKind = Literal["auto", "single", "plan_execute", "supervisor", "swarm", "workflow", "evaluator", "long_running"]
ModeName = Literal["direct", "plan", "helpers", "sandbox"]


@dataclass(frozen=True)
class LoopSettings:
    """How the agent's turn runs: the spec's `loop` (automatic-mode-and-loop-kinds.md, "Interfaces"). Each kind is
    given a fixed set of the kernel's tools (loop_kinds.py); its own settings sit beside the shared ones."""

    kind: LoopKind = "auto"
    # The loop's own limits, when the spec's `loop` sets them; None keeps the agent's (AgentSettings), so one limit has
    # one value whichever place a builder wrote it.
    max_steps: int | None = None
    max_tool_calls: int | None = None
    parallel_reads: bool | None = None
    replans: int = 2
    show_plan: bool = True
    review_plan: bool = False
    max_handoffs: int = 4
    workflow: str | None = None
    workflow_input: dict[str, str] = field(default_factory=dict[str, str])
    # The quality bar: the final answer is judged against `rubric` and sent back at most `max_rounds` times.
    rubric: str | None = None
    judge_alias: str = "judge"
    max_rounds: int = 2
    # Whether the spec has a sandbox; release 1.5.0 gives it the workspace tools.
    sandbox: bool = False


@dataclass(frozen=True)
class ModeStep:
    """One mode a turn used, named at its first use: `fixed` when the loop kind is not `auto`, so the builder set it."""

    mode: ModeName
    reason: str
    at_step: int
    fixed: bool


class PlanStep(TypedDict):
    """One step of the built-in plan (plan.py). `status` is one of plan.STATUSES, kept a plain string: a plan is stored
    with a paused turn and on a reply, and read back as it was written."""

    title: str
    status: str
    note: NotRequired[str]


class Plan(TypedDict):
    """The plan tool's checklist, stored on an interrupt and on a reply so a later turn goes on at the same step."""

    title: str
    steps: list[PlanStep]


class LoadedSkill(TypedDict):
    """A skill a turn loaded, as it is journalled and carried to the next turn (skills.loaded_entry)."""

    skillId: str
    name: str
    version: int
    matched: str
    part: NotRequired[str]
    inputs: NotRequired[dict[str, str]]
    # How a carried entry entered its turn ("picked" by the person, or loaded); journalled, kept out of the result.
    how: NotRequired[str]


class GuardrailRef(TypedDict):
    """A guardrail a turn checked, or found switched off."""

    guardrailId: str
    version: int
    name: str


class GuardrailFired(GuardrailRef):
    """The guardrail that refused, replaced or corrected an answer, the topic it found, and when: before, after or
    corrected."""

    topic: str
    when: str


@dataclass(frozen=True)
class PromptFragment:
    text: str
    # Stable fragments sit first in the system prompt so the provider's prefix cache covers them (spec 15 3.1).
    stable: bool = True


@dataclass(frozen=True)
class Guardrail:
    """A pinned guardrail version's rule: the topics the agent must not answer, and what it says instead."""

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
class SkillInput:
    """One value a skill asks for when it starts, as its version declares it (`inputs`: name, required)."""

    name: str
    required: bool = False


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
    # One named part of a skill with parts, by its slug; `slug` is then `<skill>/<part>`. Empty for a whole skill.
    part: str = ""
    # The most tokens this skill or part may hold when loaded; 0 is the reply's whole skill budget.
    budget: int = 0
    # Its steps, for a skill that runs step by step (steps.py): it is started, never loaded as text, and `instructions`
    # are then the notes shared by every step. None for a skill without steps.
    program: SkillProgram | None = None
    # What the version declares it needs to start. A skill with steps does not start while a required one is missing
    # (steps.missing_inputs). Empty until the catalog fills it from the stored version's `inputs`.
    inputs: tuple[SkillInput, ...] = ()


@dataclass(frozen=True)
class WidgetTemplate:
    """A pinned widget template version: a tree of catalogue primitives with `$bind` pointers into data that
    must match `schema`. `use_when` is the line the present tool's description gives the model."""

    widget_id: str
    version: int
    name: str
    use_when: str
    tree: Json
    schema: Json


# Above this many granted tools an agent finds its tools by searching: no schema is sent until a search
# reveals it. OPS_TOOL_SEARCH_ABOVE changes it per deployment, with the install flag tool_search on.
TOOL_SEARCH_ABOVE = 20
# The heading the never rules are written under unless the workspace's list renames it.
NEVER_HEADING = "Never"


@dataclass(frozen=True)
class AgentSettings:
    agent_id: str
    version: int
    instructions: list[PromptFragment]
    model_alias: str
    # None: no cap. A real agent may need many; seeds and tests set low ones.
    max_tool_calls: int | None = 6
    # Model requests in one turn (the loop's steps). Always a number: an uncapped loop would spend real calls until
    # the deadline, so an agent with no cap set runs on the platform default. Above one, the last step offers no tool,
    # so a turn always has a step left to answer in.
    max_steps: int = 8
    # Calls to the kernel's own tools (present, search_tools, load_skill) in one turn, all kinds together; past it they
    # answer "answer in text now" and are withdrawn. None: no cap. They reach no system, so max_tool_calls never
    # charges them, and without this a model can spend every step on them.
    max_builtin_calls: int | None = 3
    # Check the finished answer with no model call (answer_check.py): an error code, a stray last word, a question
    # after reads that all succeeded, uncited knowledge. A defect gets one correction call naming it.
    end_check: bool = False
    # More granted tools than this and they are searched for, not all offered; 0 means always search. None is
    # off, every tool offered: the install flag tool_search is off by default.
    tool_search_above: int | None = None
    # A caller's temperature within the agent's limits; None leaves the model's default.
    temperature: float | None = None
    # Checked before and after the answer by a classification call; none means today's path, no extra call.
    guardrails: list[Guardrail] = field(default_factory=list[Guardrail])
    # Pinned guardrails the builder switched off: never checked (no classification call), named on the turn's result
    # so a turn never looks protected by them.
    guardrails_off: list[Guardrail] = field(default_factory=list[Guardrail])
    skills: list[Skill] = field(default_factory=list[Skill])
    # Widgets the agent may fill, whether it may compose layouts from the catalogue, and how many widgets one
    # turn may show (None: no cap; the agent's own setting is the only limit).
    widgets: list[WidgetTemplate] = field(default_factory=list[WidgetTemplate])
    compose: bool = False
    widgets_per_turn: int | None = None
    # Mask personal data in what the turn shows and returns (the agent's redactPii); the model sees it all.
    redact_pii: bool = False
    # The brief's never rules: written last in the prompt, after everything else, whoever wrote the rest of it.
    never: list[str] = field(default_factory=list[str])
    # The heading they are written under: the never section's label in the workspace's list when the version was saved.
    never_heading: str = NEVER_HEADING
    # How hard the model thinks ("low", "medium", "high"); None leaves the model's default and sends no setting.
    thinking: str | None = None
    # Off: the model is asked to make one tool call at a time. Writes run one at a time whatever this says.
    parallel_reads: bool = True
    # The model settings the agent version saved, by knob name (temperature, top_p, top_k, max_tokens,
    # thinking_budget, reasoning_effort), checked against its alias's knobs when saved. models-service fits each call
    # to the alias's model again (catalog.fit), since an alias can move to a model with other limits.
    model_settings: dict[str, float | int | str] = field(default_factory=dict[str, float | int | str])


@dataclass(frozen=True)
class ToolGrant:
    name: str
    server: str
    description: str
    access: Access
    input_schema: Json
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
class BaseAnswer:
    """A knowledge base's answer settings (kb-service's answer section). `withhold_uncited`: an answer that uses the
    base and cites none of its passages is replaced by `no_answer_message`, which is also said when nothing is found.
    A base giving back pieces only (`shape` "chunks") leaves the answer to the agent and is never withheld."""

    shape: str
    withhold_uncited: bool
    no_answer_message: str

    @property
    def withholds(self) -> bool:
        return self.withhold_uncited and self.shape != "chunks"

    @classmethod
    def of(cls, a: Json) -> BaseAnswer:
        """A base's answer settings as kb-service serves them (camelCase)."""
        return cls(
            shape=str(a.get("shape") or "answer_with_citations"),
            withhold_uncited=bool(a.get("withholdUncited")),
            no_answer_message=str(a.get("noAnswerMessage") or ""),
        )


class KnowledgeFound(list[Passage]):
    """A knowledge search's passages, best first, with each searched base's answer settings by id in search order. A
    plain list of passages is a search whose bases set no answer rule."""

    def __init__(self, passages: list[Passage], answers: dict[str, BaseAnswer] | None = None) -> None:
        super().__init__(passages)
        self.answers: dict[str, BaseAnswer] = dict(answers or {})


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
    input: Json
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
    loaded_skills: list[LoadedSkill] = field(default_factory=list[LoadedSkill])
    # The plan as it stood at the pause (plan.py), so the resumed turn goes on at the same step.
    plan: Plan | None = None
    # The running-skill record at the pause, unmasked: the resumed turn goes on at the same step. None on a pause
    # stored before skills had steps.
    run: SkillRunState | None = None
    # By skill id, the step tools a skill stopped before the pause still holds: the resumed turn is the same reply, so
    # they stay off offer in it. Empty on a pause stored without it.
    held: dict[str, list[str]] = field(default_factory=dict[str, list[str]])
    # A pause that belongs to another turn this call ran, a helper agent's on its own thread ({threadId,
    # interruptId}): deciding it decides that turn's call, and this turn goes on once that one has answered.
    nested: Json | None = None


@dataclass(frozen=True)
class Resume:
    interrupt: Interrupt
    decision: Literal["approved", "rejected"]
    reason: str | None = None
    approval_token: str | None = None


# The knowledge id an attached file's passages carry: a citation of one names a Files file, not a knowledge item.
ATTACHMENT_KB = "attachment"


@dataclass(frozen=True)
class AttachedFile:
    """A file the person attached to the conversation, as the turn names it to the model: its name, its file id, and
    why it could not be read when it could not. The text that was read arrives as `TurnRequest.attached`."""

    file_id: str
    name: str
    unread: str | None = None


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
    # The agent's "all team knowledge bases" option: its search_knowledge calls may search every base of its team.
    # Off, they search only `kb_ids`, as grounding does.
    all_team_knowledge: bool = False
    # Files attached to the conversation, named in their own data block whether or not their text could be read.
    attachments: list[AttachedFile] = field(default_factory=list[AttachedFile])
    # The attached files' text, page by page (kb_id ATTACHMENT_KB), whole within the turn's share: shown in the
    # attachments block and numbered before any knowledge passage, so the model cites a page of a file it was given.
    attached: list[Passage] = field(default_factory=list[Passage])
    # The conversation named knowledge bases and the agent no longer holds any of them: the turn says so and does not
    # call the model, which would otherwise answer from its own knowledge, uncited.
    knowledge_withdrawn: bool = False
    # Whether the person asked this turn for knowledge (the conversation named knowledge bases), so finding none is a
    # no-answer. None: whenever `kb_ids` is set, as a workflow's knowledge step asks.
    knowledge_asked: bool | None = None
    variables: dict[str, str] = field(default_factory=dict[str, str])
    resume: Resume | None = None
    # On-match skills an earlier turn of the conversation loaded ({skillId, version, name, matched}): this turn keeps
    # them loaded with their bodies in the system prompt, so a follow-up does not load them again.
    carried_skills: list[Json] = field(default_factory=list[Json])
    # What earlier turns of the conversation read, one line each, so a follow-up answers from them, not a new read.
    earlier_reads: list[str] = field(default_factory=list[str])
    # A plan an earlier turn left unfinished (a Connect card paused it): this turn goes on from its first open step.
    carried_plan: Json | None = None
    # The running-skill record the reply before this one returned (TurnResult.run): this turn goes on at its step.
    carried_run: SkillRunState | None = None
    deadline_seconds: float = 120.0
    # A JSON Schema the turn's answer must match (a workflow's agent step): the model returns structured output
    # through the call, validated against it, on `TurnResult.output`; a mismatch finishes with `schema_error`.
    output_schema: Json | None = None
    loop: LoopSettings = field(default_factory=LoopSettings)


@dataclass
class ToolCallRecord:
    tool_call_id: str
    key: str
    tool: str
    server: str
    access: Access
    input: Json
    input_hash: str
    status: Literal["running", "ok", "error", "gated"]
    output: Any = None
    duration_ms: int = 0
    view: Json | None = None
    # Answered from what this conversation already read (tool_cache.py); the system was not called.
    cached: bool = False
    # Whose login of the app the call ran as, from the tool's outcome; None for a call with no account.
    signed_in: Json | None = None


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
        # The model port refused a call at the budget the reply spends from (ports.BudgetReachedError).
        "budget_reached",
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
    guardrail: GuardrailFired | None = None
    # Text a guardrail kept from the person (a withdrawn or rewritten answer, or the unchecked part of a guarded
    # turn that ended early). For the run's audit record only; never shown in the conversation.
    withheld: str | None = None
    # Text the person saw as it streamed and a guardrail then replaced (a refused or rewritten answer, or the unchecked
    # part of a turn that ended early). Distinct from `withheld`, which was never shown. Audit record only.
    retracted: str | None = None
    # Skills this turn loaded, always-on ones first: {skillId, name, version, matched}.
    skills: list[LoadedSkill] = field(default_factory=list[LoadedSkill])
    # The guardrails this turn checked and the pinned ones switched off: {guardrailId, version, name} each.
    guardrails_checked: list[GuardrailRef] = field(default_factory=list[GuardrailRef])
    guardrails_off: list[GuardrailRef] = field(default_factory=list[GuardrailRef])
    # The skill with steps this conversation is running and the ones that ended, after this turn, whichever way the
    # turn ended. None when the agent has no skill with steps and the request carried no record.
    run: SkillRunState | None = None
    # The modes the turn used, in the order each was first named (modes.py).
    modes: list[ModeStep] = field(default_factory=list[ModeStep])
    # Calls refused this turn because no plan was shown first; counted once per turn.
    plan_required: bool = False
    # Whether the answer met the loop's quality bar; None when the loop sets none.
    bar_met: bool | None = None
