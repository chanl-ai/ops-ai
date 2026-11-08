"""The built-in `plan` tool: the model's checklist for an ask that takes more than one lookup, kept current as it works.

Each call sends the whole list (title, three to seven steps, each todo, doing, done, blocked or skipped). The checks
keep it honest: one step doing or blocked at most, a step never moves back, a done step's title never changes, and the
plan is replaced (`replan`) at most twice a turn. A refused call returns the rule and leaves the plan on screen as it
was. The plan is drawn in the existing `steps` shape, one part per turn that each call redraws; once every step is done
or skipped its title reads "Did N steps". Titles and notes are masked as reply text is.
"""

from __future__ import annotations

from typing import Any, cast

from .pii import mask
from .types import ToolGrant

NAME = "plan"
SERVER = "kernel"
STATUSES = ("todo", "doing", "done", "blocked", "skipped")
# The order a step moves in; blocked sits beside doing, as a paused step goes on from where it stopped.
RANK = {"todo": 0, "doing": 1, "blocked": 1, "done": 2, "skipped": 2}
FINISHED = ("done", "skipped")
MIN_STEPS, MAX_STEPS = 3, 7
MAX_REPLANS = 2
TITLE_CHARS = 120
# The steps shape's states (console lib/types/widgets.ts StepState).
SHOWN = {"todo": "pending", "doing": "running", "done": "done", "blocked": "failed", "skipped": "done"}
SKIPPED = " (skipped)"

GRANT = ToolGrant(
    NAME,
    SERVER,
    "Keep a short checklist the person sees while you work, for an ask that needs a chain of lookups (a later one "
    "depends on an earlier result), more than one app, or a change. Never for one lookup or reads that answer one "
    "question together. Send the whole list every time: a title and 3 to 7 steps, each {title, status, note?} with "
    "status todo, doing, done, blocked or skipped. Mark a step doing when you start it and done when its reads are "
    "back, in the same step as the next reads; one step doing at a time; a step never goes back. Set replan true to "
    "replace the steps after a step failed, at most twice.",
    "read",
    {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "steps": {
                "type": "array",
                "minItems": MIN_STEPS,
                "maxItems": MAX_STEPS,
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "status": {"type": "string", "enum": list(STATUSES)},
                        "note": {"type": "string"},
                    },
                    "required": ["title", "status"],
                },
            },
            "replan": {"type": "boolean"},
        },
        "required": ["title", "steps"],
    },
)


def _text(value: Any) -> str:
    return mask(str(value or "").strip())[:TITLE_CHARS]


def given(arguments: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """The plan the call sends, cleaned and masked, or why its shape is refused."""
    raw = arguments.get("steps")
    if not isinstance(raw, list) or not MIN_STEPS <= len(cast(list[Any], raw)) <= MAX_STEPS:
        return None, f"A plan has {MIN_STEPS} to {MAX_STEPS} steps; for fewer, make the reads without a plan."
    steps: list[dict[str, Any]] = []
    for s in cast(list[Any], raw):
        step = cast(dict[str, Any], s) if isinstance(s, dict) else {}
        status = str(step.get("status") or "")
        if not step.get("title") or status not in STATUSES:
            return None, f"Each step is {{title, status}} with status one of {', '.join(STATUSES)}."
        steps.append(
            {
                "title": _text(step["title"]),
                "status": status,
                **({"note": _text(step["note"])} if step.get("note") else {}),
            }
        )
    return {"title": _text(arguments.get("title")) or "Plan", "steps": steps}, None


def check(before: dict[str, Any] | None, plan: dict[str, Any], *, replan: bool, replans: int) -> str | None:
    """Why `plan` cannot follow `before`, or None. A replan replaces the open steps and keeps the finished ones."""
    steps = cast(list[dict[str, Any]], plan["steps"])
    if sum(s["status"] in ("doing", "blocked") for s in steps) > 1:
        return "One step is doing (or blocked) at a time; mark it done before the next one starts."
    if before is None:
        return None
    old = cast(list[dict[str, Any]], before["steps"])
    if replan:
        if replans >= MAX_REPLANS:
            return f"The plan was replaced {MAX_REPLANS} times this reply; finish with what you have."
        kept = [s for s in old if s["status"] in FINISHED]
        if [(s["title"], s["status"]) for s in steps[: len(kept)]] != [(s["title"], s["status"]) for s in kept]:
            return "A new plan keeps the finished steps first, as they were."
        return None
    if len(steps) != len(old):
        return "Send every step of the plan; to change the steps, set replan true."
    for was, now in zip(old, steps, strict=True):
        if was["status"] in FINISHED and now["title"] != was["title"]:
            return f'The finished step "{was["title"]}" keeps its title.'
        if RANK[now["status"]] < RANK[was["status"]]:
            return f'"{was["title"]}" is {was["status"]} and cannot go back to {now["status"]}.'
    return None


def finished(plan: dict[str, Any]) -> bool:
    return all(s["status"] in FINISHED for s in cast(list[dict[str, Any]], plan["steps"]))


def current(plan: dict[str, Any]) -> str | None:
    """The step being worked: the one doing or blocked, else the first not finished."""
    steps = cast(list[dict[str, Any]], plan["steps"])
    live = next((s for s in steps if s["status"] in ("doing", "blocked")), None)
    nxt = live or next((s for s in steps if s["status"] not in FINISHED), None)
    return str(nxt["title"]) if nxt else None


def answer(plan: dict[str, Any]) -> dict[str, Any]:
    """What the model is told after a call: the step it is on and how many are left."""
    left = sum(s["status"] not in FINISHED for s in cast(list[dict[str, Any]], plan["steps"]))
    return {"ok": True, "current": current(plan), "left": left}


def part(plan: dict[str, Any]) -> dict[str, Any]:
    """The plan as the steps shape: a skipped step reads done with "(skipped)", a blocked one failed with its note."""
    steps = cast(list[dict[str, Any]], plan["steps"])
    rows = [
        {
            "title": s["title"]
            + (SKIPPED if s["status"] == "skipped" else "")
            + (f": {s['note']}" if s.get("note") and s["status"] == "blocked" else ""),
            "state": SHOWN[s["status"]],
        }
        for s in steps
    ]
    title = f"Did {len(steps)} steps" if finished(plan) else str(plan["title"])
    return {"type": "widget", "id": "", "shape": "steps", "data": rows, "hint": {"title": title}}


def paused(plan: dict[str, Any], why: str) -> dict[str, Any]:
    """The plan when the turn stops before it finished: the step being worked is blocked, with why."""
    steps = [dict(s) for s in cast(list[dict[str, Any]], plan["steps"])]
    live = next((s for s in steps if s["status"] in ("doing", "blocked")), None)
    live = live or next((s for s in steps if s["status"] not in FINISHED), None)
    if live is not None:
        live["status"], live["note"] = "blocked", why
    return {**plan, "steps": steps}


def from_part(part: dict[str, Any]) -> dict[str, Any] | None:
    """A plan read back from its drawn part, for the next turn to go on with; None when it was finished."""
    back = {"pending": "todo", "running": "doing", "done": "done", "failed": "blocked"}
    steps: list[dict[str, Any]] = []
    for row in cast(list[dict[str, Any]], part.get("data") or []):
        title, status = str(row.get("title") or ""), back.get(str(row.get("state")), "todo")
        if title.endswith(SKIPPED):
            title, status = title[: -len(SKIPPED)], "skipped"
        steps.append({"title": title, "status": status})
    title = str(cast(dict[str, Any], part.get("hint") or {}).get("title") or "Plan")
    plan = {"title": title, "steps": steps}
    return None if not steps or finished(plan) else plan


def prompt(plan: dict[str, Any]) -> str:
    """The plan an earlier turn left unfinished, for this turn to go on with."""
    lines = "\n".join(f"- {s['title']}: {s['status']}" for s in cast(list[dict[str, Any]], plan["steps"]))
    return (
        f"## Plan in progress: {plan['title']}\n\n{lines}\n\nGo on from the first step not done (a blocked step waited "
        "for the person, who has now answered): send the whole plan with that step doing, then its reads."
    )
