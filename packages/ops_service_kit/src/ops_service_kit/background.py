"""The shape every service's `/health/background` answers in, and agents-service's Background page reads (c-516)."""

from __future__ import annotations

from typing import Literal

from .http import Out

ProcessState = Literal["running", "late", "stopped", "not_reported"]


class BackgroundProcessOut(Out):
    key: str
    service: str
    title: str
    does: str
    every_seconds: float | None
    state: ProcessState
    instances: int
    last_run_at: float | None
    next_run_at: float | None
    done_hour: int
    waiting: int | None
    last_error: str | None
    last_error_at: float | None


class BackgroundHealthOut(Out):
    processes: list[BackgroundProcessOut]
