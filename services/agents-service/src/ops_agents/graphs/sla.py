"""A human step's SLA: its settings, and the review loop that turns a timeout into one of three outcomes.

The step raises an interrupt carrying its settings; the Runtime's timer poller resumes it with
`{"decision": "timeout", "timer": "breach" | "maxWait"}` when a timer falls due. On a breach the step's `onTimeout`
runs: `reassign` and `escalate` raise the interrupt again to another group, `reject` ends the review as rejected. A
`maxWait` timeout always rejects. Any other decision is a reviewer's and ends the loop as it is.

LangGraph re-runs the node on every resume and replays the earlier interrupts' answers in order, so the loop must
take the same path for the same answers: it reads nothing but the settings and those answers.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd])\s*$")


def seconds(duration: str | float) -> float:
    """`"2s"`, `"30m"`, `"4h"`, `"3d"`, or a number of seconds."""
    if isinstance(duration, int | float):
        return float(duration)
    m = _DURATION.match(duration)
    if not m:
        raise ValueError(f"Not a duration: {duration!r} (use 2s, 30m, 4h or 3d)")
    return float(m.group(1)) * _UNITS[m.group(2)]


class HumanSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)

    group: str = "reviewers"
    sla: str | float | None = None
    warn_at: str | float | None = Field(default=None, alias="warnAt")
    on_timeout: Literal["reassign", "escalate", "reject"] = Field(default="escalate", alias="onTimeout")
    escalate_to: str | None = Field(default=None, alias="escalateTo")
    reassign_to: str | None = Field(default=None, alias="reassignTo")
    max_wait_days: float | None = Field(default=None, alias="maxWaitDays")


def sla_block(s: HumanSettings, *, group: str, round_: int, escalated: bool) -> dict[str, Any]:
    """What the interrupt tells the timer writer. An escalated review has no breach or warning, only its max wait."""
    return {
        "group": group,
        "round": round_,
        "escalated": escalated,
        "onTimeout": s.on_timeout,
        "escalateTo": s.escalate_to,
        "reassignTo": s.reassign_to or s.group,
        "slaSeconds": None if escalated or s.sla is None else seconds(s.sla),
        "warnAtSeconds": None if escalated or s.warn_at is None else seconds(s.warn_at),
        "maxWaitSeconds": None if s.max_wait_days is None else s.max_wait_days * 86400,
    }


def review_loop(
    payload: dict[str, Any], s: HumanSettings, raise_interrupt: Callable[[dict[str, Any]], Any]
) -> dict[str, Any]:
    group, round_, escalated = s.group, 0, False
    while True:
        decision: dict[str, Any] = raise_interrupt(
            {**payload, "sla": sla_block(s, group=group, round_=round_, escalated=escalated)}
        )
        if decision.get("decision") != "timeout":
            return decision
        if decision.get("timer") == "maxWait":
            return {"decision": "rejected", "reason": "No decision within the step's maximum wait.", "timedOut": True}
        if s.on_timeout == "reject" or (s.on_timeout == "escalate" and escalated):
            return {"decision": "rejected", "reason": "The review's SLA passed with no decision.", "timedOut": True}
        round_ += 1
        if s.on_timeout == "reassign":
            group = s.reassign_to or group
        else:
            group, escalated = s.escalate_to or group, True
