"""The audit entry of a schedule save or clear: its action and the one line the Audit page shows, in words from the
rule kinds, so the entry says what the schedule was and became without a reader opening the workflow."""

from __future__ import annotations

from typing import Literal, TypedDict

from ops_store.schedule import KINDS

from ..store.schedules import Rule

SAVE = "workflow.schedule.save"
CLEAR = "workflow.schedule.clear"


class Entry(TypedDict):
    action: str
    summary: str
    detail: dict[str, str | None]


def entry(
    kind: Literal["save", "clear"], workflow_name: str, step: str, before: Rule | None, after: Rule | None
) -> Entry:
    """`before` is the rule replaced (None for a first save), `after` the rule saved (None for a clear)."""
    was = KINDS.words(before) if before else None
    now = KINDS.words(after) if after else None
    if kind == "clear":
        summary = f"Cleared the schedule of {workflow_name}; it was {was}"
    elif was is None:
        summary = f"Set the schedule of {workflow_name} to {now}"
    else:
        summary = f"Changed the schedule of {workflow_name} from {was} to {now}"
    return {
        "action": CLEAR if kind == "clear" else SAVE,
        "summary": summary,
        "detail": {"step": step, "before": was, "after": now},
    }
