"""Events the kernel emits while a turn runs (spec 15 6.1); the caller maps them to its stream protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .types import CitationRef, Interrupt, ToolCallRecord, TurnResult

Phase = Literal["thinking", "retrieving", "calling_tool", "writing"]


@dataclass(frozen=True)
class StatusChanged:
    phase: Phase


@dataclass(frozen=True)
class TextDelta:
    delta: str


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


KernelEvent = StatusChanged | TextDelta | ToolInputAvailable | ToolOutput | CitationsReady | Interrupted | TurnFinished
