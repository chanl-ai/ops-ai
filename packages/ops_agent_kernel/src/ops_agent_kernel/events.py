"""Events the kernel emits while a turn runs (spec 15 6.1); the caller maps them to its stream protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .types import CitationRef, Interrupt, ToolCallRecord, TurnResult

# checking: a guarded answer is written and being checked; nothing of it is shown until it passes.
Phase = Literal["thinking", "retrieving", "calling_tool", "writing", "checking"]


@dataclass(frozen=True)
class StatusChanged:
    phase: Phase


@dataclass(frozen=True)
class TextDelta:
    delta: str


@dataclass(frozen=True)
class TextReplaced:
    """The text streamed so far is replaced by `text`: a guarded answer shown as it was written that its after-answer
    check then corrected or refused, or cleared when the turn ended before the check could run."""

    text: str


@dataclass(frozen=True)
class ToolInputAvailable:
    call: ToolCallRecord


@dataclass(frozen=True)
class ToolOutput:
    call: ToolCallRecord


@dataclass(frozen=True)
class CitationsReady:
    citations: list[CitationRef]


@dataclass(frozen=True)
class Interrupted:
    interrupt: Interrupt


@dataclass(frozen=True)
class TurnFinished:
    result: TurnResult


@dataclass(frozen=True)
class SkillLoaded:
    """A pinned skill version entered the turn: always-on at the start, on-match when load_skill returned it."""

    skill_id: str
    version: int
    name: str
    matched: str


KernelEvent = (
    StatusChanged
    | TextDelta
    | TextReplaced
    | ToolInputAvailable
    | ToolOutput
    | CitationsReady
    | SkillLoaded
    | Interrupted
    | TurnFinished
)
