"""A skill's step program and the record of the one running in a conversation.

The program is what a skill version stores beside its instructions (`notWhen`, `steps`, `exit`, `returns`,
`success`). The record is what the kernel writes while a skill with steps runs: the step it is on, each step's
outcome, and the program of the version it started on, so a conversation finishes a skill on that version after the
agent pins a newer one. Both are defined here because the kernel writes the record, agents-service journals it, a chat
message carries it to the console and the SDKs generate it.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator
from pydantic.alias_generators import to_camel

RefKind = Literal["tool", "knowledge", "skill", "agent", "workflow"]
# An id ends in a letter, digit or underscore, so the full stop after "with @tool:open_dispute." is text.
REF_ID = r"[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,126}[A-Za-z0-9_])?"
# A reference as it is written inside text: `@tool:lookup_customer`. It does not start after a letter, digit,
# underscore or `@` (an email address is not one). The console's editor reads text by the same rule.
REF_TOKEN = re.compile(rf"(?<![\w@])@(tool|knowledge|skill|agent|workflow):({REF_ID})")
EXIT_NAME = r"^[a-z][a-z0-9_]{0,31}$"
# Every skill with steps can end as one of these without declaring it.
BUILT_IN_EXITS = ("done", "failed")
MAX_STEPS = 30
# A step result kept on the record is at most this many characters of JSON; a longer one is left out.
RESULT_MAX = 2000
HISTORY_MAX = 5

Line = Annotated[str, Field(min_length=1, max_length=300)]


class RunModel(BaseModel):
    """camelCase where it is stored and sent, snake_case in Python; a key it does not name is refused."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


# An agent or a workflow an agent may use is spelled three ways, all owned here: a reference names it by its bare id
# (`@agent:ag_x`), an agent's grant and the tools directory store it as `agent:ag_x`, and the model calls the tool
# `agent__ag_x` (a tool name allows no colon). The service builds its grants with `called_as` and the kernel reads
# them with `hands_to_agent` and `grant_token`, so the two never spell a name apart.
AGENT_TOOL_PREFIX = "agent__"
WORKFLOW_TOOL_PREFIX = "workflow__"
_CALLED: dict[str, str] = {"agent": AGENT_TOOL_PREFIX, "workflow": WORKFLOW_TOOL_PREFIX}


def called_as(kind: str, ref_id: str) -> str:
    """The name of the tool the model calls to ask agent `ref_id` or start workflow `ref_id`."""
    return f"{_CALLED[kind]}{ref_id}"


def hands_to_agent(tool_name: str) -> bool:
    """Whether a called tool asks another agent."""
    return tool_name.startswith(AGENT_TOOL_PREFIX)


def grant_token(tool_name: str) -> str | None:
    """The reference a text writes for an agent's or a workflow's tool (`@agent:ag_x`); None for any other tool."""
    for kind, prefix in _CALLED.items():
        if tool_name.startswith(prefix):
            return f"@{kind}:{tool_name.removeprefix(prefix)}"
    return None


class Ref(RunModel):
    """Something a text or a step names: a tool, a knowledge base, a skill, an agent or a workflow, by its id. An
    agent or a workflow is named by its bare id; `grant` and `tool_name` are its two other spellings."""

    kind: RefKind
    id: str = Field(pattern=rf"^{REF_ID}$")

    @property
    def token(self) -> str:
        return f"@{self.kind}:{self.id}"

    @property
    def tool_name(self) -> str | None:
        """The name of the tool a step calls for this reference; None for a skill or a knowledge base."""
        if self.kind == "tool":
            return self.id
        return called_as(self.kind, self.id) if self.kind in _CALLED else None

    @property
    def grant(self) -> str | None:
        """What an agent's grant and the tools directory store for this reference; None for a skill or a knowledge
        base."""
        if self.kind == "tool":
            return self.id
        return f"{self.kind}:{self.id}" if self.kind in ("agent", "workflow") else None

    @classmethod
    def parse(cls, token: str) -> Ref | None:
        m = REF_TOKEN.fullmatch(token.strip())
        return cls.model_validate({"kind": m.group(1), "id": m.group(2)}) if m else None

    @classmethod
    def found_in(cls, text: str) -> list[Ref]:
        """Every reference written in `text`, in order, each once."""
        seen: dict[str, Ref] = {}
        for m in REF_TOKEN.finditer(text):
            seen.setdefault(m.group(0), cls.model_validate({"kind": m.group(1), "id": m.group(2)}))
        return list(seen.values())


class StepCheck(RunModel):
    """What must hold before a step is done. `by` is set when the skill is saved: a rule is run on the step's result
    in code, a sentence is confirmed by the model."""

    text: str = Field(min_length=1, max_length=300)
    by: Literal["rule", "model"] | None = None


class IfNot(RunModel):
    """What happens when a step's check fails: ask again, go to another step, or end the skill with an exit."""

    action: Literal["retry", "goto", "exit"] = "retry"
    step: int | None = Field(default=None, ge=1, le=MAX_STEPS)
    exit: str | None = Field(default=None, pattern=EXIT_NAME)
    retries: int = Field(default=1, ge=0, le=3)

    @model_validator(mode="after")
    def _fields_fit_the_action(self) -> Self:
        needs = {"retry": None, "goto": "step", "exit": "exit"}[self.action]
        for name in ("step", "exit"):
            given = getattr(self, name) is not None
            if given != (name == needs):
                raise ValueError(
                    f"{name} is {'required' if name == needs else 'not allowed'} when action is {self.action}"
                )
        return self


class SkillStep(RunModel):
    do: str = Field(min_length=1, max_length=600)
    use: Ref | None = None
    check: StepCheck | None = None
    if_not: IfNot | None = None
    # The builder's lock on the step's tool: it is reachable only as this step even when it is a read. A tool that
    # changes something is kept to its step with or without it. Stored only when on, and only on a step that runs a
    # tool.
    locked: bool | None = None

    @model_validator(mode="after")
    def _lock_needs_a_tool(self) -> SkillStep:
        if not self.locked or self.use is None or self.use.tool_name is None:
            self.locked = None
        return self


class ReturnField(RunModel):
    """One value a skill hands back when it ends."""

    name: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    type: Literal["text", "number", "yes_no"]
    description: str = Field(default="", max_length=300)
    required: bool = True

    @field_validator("name")
    @classmethod
    def _not_reserved(cls, name: str) -> str:
        if name == "exit":
            raise ValueError("exit is the name of the skill's exit and cannot name a result")
        return name


class SkillProgram(RunModel):
    """A skill's steps and what it ends with. A skill with no steps has no program and is loaded as text."""

    not_when: str = Field(default="", max_length=1024)
    steps: list[SkillStep] = Field(default_factory=list[SkillStep], max_length=MAX_STEPS)
    exit: dict[str, str] = Field(default_factory=dict[str, str], max_length=8)
    returns: list[ReturnField] = Field(default_factory=list[ReturnField], max_length=12)
    success: list[Line] = Field(default_factory=list[Line], max_length=8)

    @field_validator("exit")
    @classmethod
    def _exit_names(cls, exits: dict[str, str]) -> dict[str, str]:
        for name, meaning in exits.items():
            if not re.fullmatch(EXIT_NAME, name):
                raise ValueError(f"exit name {name!r} must be lower-case letters, digits and underscores")
            if not 1 <= len(meaning) <= 300:
                raise ValueError(f"exit {name!r} needs a meaning of 1 to 300 characters")
        return exits

    def exits(self) -> set[str]:
        return {*self.exit, *BUILT_IN_EXITS}

    def targets(self) -> set[str]:
        """The tools this program's steps call, by the name each is granted under."""
        return {name for s in self.steps if s.use is not None and (name := s.use.tool_name) is not None}

    def locked(self) -> set[str]:
        """The tools a builder locked to their step (`SkillStep.locked`), by the name each is granted under."""
        return {name for s in self.steps if s.locked and s.use is not None and (name := s.use.tool_name) is not None}


class StepResult(RunModel):
    """How a step came out. `passed` is None while a step's tool has run and the model has yet to confirm its
    sentence check."""

    passed: bool | None = None
    value: JsonValue | None = None
    truncated: bool = False


class SubRun(RunModel):
    """A skill a step started, one level deep; when it ends, the step that started it (`return_to`) gets its exit
    and results."""

    skill_id: str
    version: int
    slug: str
    name: str
    step: int = Field(ge=1)
    steps_total: int = 0
    step_text: str = ""
    inputs: dict[str, str] = Field(default_factory=dict[str, str])
    masked_inputs: list[str] = Field(default_factory=list[str])
    results: dict[str, StepResult] = Field(default_factory=dict[str, StepResult])
    attempts: dict[str, int] = Field(default_factory=dict[str, int])
    return_to: int
    program: SkillProgram
    rules: str = ""


class RunningSkill(RunModel):
    skill_id: str
    version: int
    slug: str
    name: str
    step: int = Field(ge=1)
    steps_total: int
    step_text: str
    started_by: Literal["menu", "model"]
    inputs: dict[str, str] = Field(default_factory=dict[str, str])
    # The inputs whose value here is a placeholder, because the record was masked on its way out of a reply. A rule
    # that reads one does not run: it would compare the placeholder.
    masked_inputs: list[str] = Field(default_factory=list[str])
    # Keyed by the step number as text.
    results: dict[str, StepResult] = Field(default_factory=dict[str, StepResult])
    attempts: dict[str, int] = Field(default_factory=dict[str, int])
    sub: SubRun | None = None
    # The steps and shared notes of the version that started, which the skill finishes on.
    program: SkillProgram
    rules: str = ""


# Why a skill ended when it did not finish: a check did not pass, a person rejected its action, a step could not be
# done (its tool failed, or the skill it runs could not start), another skill holds its step's tool, or the model
# called the exit itself.
EndedWhy = Literal["check", "denied", "error", "held", "exit"]


class EndedSkill(RunModel):
    """How a skill ended, and why: the one record of it. The kernel writes it; the chat draws the ending from it and
    the kernel reads it to keep a skill it ended from starting again in the same reply."""

    skill_id: str
    version: int
    name: str
    # An exit name, or `switched` when another skill took its place.
    ended: str
    at_step: int
    # The tools its steps and its sub-skills' steps call, kept unless it ended as done or switched: they are not
    # offered for the rest of the reply it ended in. What a failed check or a denied call holds beyond that reply
    # is in `SkillRunState.holds`, because this list is capped.
    tools: list[str] = Field(default_factory=list[str])
    # The results it was ended with, by name.
    returns: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    # Set while the record is the one of the reply the skill ended in; cleared when the next reply starts. None of
    # the four fields below is on a record written before endings carried a reason.
    in_reply: bool = False
    # None when it ended as done or switched.
    why: EndedWhy | None = None
    # The text of the check that did not pass, when that is why.
    check: str | None = None
    # What the skill's author wrote that this exit means; None for done, failed and switched.
    meaning: str | None = None


class Hold(RunModel):
    """Tools kept from every other skill, and from a call with no skill running, because a step's check did not
    pass or a person denied its call. The skill that holds them is never kept from them itself. The hold ends when
    that skill passes the same step, or when the agent no longer has this version of it."""

    skill_id: str
    version: int
    slug: str
    name: str
    # The step whose check failed or whose call was denied: its number, then a dot and the step of the skill it
    # runs when that is where it happened ("2", "2.1").
    step: str
    denied: bool = False
    # The tools of the steps after it, those of skills they run included; with the denied tool when a call was
    # denied; never the tool of the step whose check failed, so the check can always be run again.
    tools: list[str] = Field(default_factory=list[str])


class SkillRunState(RunModel):
    """The skill running in a conversation, if any, and the newest few that ended, oldest first."""

    running: RunningSkill | None = None
    history: list[EndedSkill] = Field(default_factory=list[EndedSkill])
    # Kept apart from `history`, which drops its oldest entries: a hold lasts as long as the thread.
    holds: list[Hold] = Field(default_factory=list[Hold])
