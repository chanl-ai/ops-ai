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
# A reference as it is written inside text: `@tool:lookup_customer`.
REF_TOKEN = re.compile(r"@(tool|knowledge|skill|agent|workflow):([A-Za-z0-9][A-Za-z0-9_.-]{0,127})")
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


class Ref(RunModel):
    """Something a text or a step names: a tool, a knowledge base, a skill, an agent or a workflow, by its id. An
    agent or a workflow is named by its bare id; a grant stores them as `agent:<id>` and `workflow:<id>`."""

    kind: RefKind
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")

    @property
    def token(self) -> str:
        return f"@{self.kind}:{self.id}"

    @property
    def tool_name(self) -> str | None:
        """The name of the tool a step calls for this reference; None for a skill or a knowledge base."""
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
    # Keyed by the step number as text.
    results: dict[str, StepResult] = Field(default_factory=dict[str, StepResult])
    attempts: dict[str, int] = Field(default_factory=dict[str, int])
    sub: SubRun | None = None
    # The steps and shared notes of the version that started, which the skill finishes on.
    program: SkillProgram
    rules: str = ""


class EndedSkill(RunModel):
    skill_id: str
    version: int
    name: str
    # An exit name, or `switched` when another skill took its place.
    ended: str
    at_step: int
    # The tools its steps call, kept when it ended as failed: they stay withheld until the skill starts again.
    tools: list[str] = Field(default_factory=list[str])


class SkillRunState(RunModel):
    """The skill running in a conversation, if any, and the newest few that ended, oldest first."""

    running: RunningSkill | None = None
    history: list[EndedSkill] = Field(default_factory=list[EndedSkill])
