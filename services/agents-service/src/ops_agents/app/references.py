"""What a builder can mention with @ in an agent's brief or a skill's steps: tools, knowledge bases, skills, agents
and workflows, grouped by kind. One search feeds the picker; the same reply resolves the ids a saved text already
names to their labels.

It is handed what the team offers (`Candidate`) and what the agent or skill already holds (`Context`), and decides
nothing about access: the route passes only the kinds the caller may view.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, TypedDict

from ops_contracts.skill_run import RefKind

KINDS: tuple[RefKind, ...] = ("tool", "knowledge", "skill", "agent", "workflow")
LABELS: dict[RefKind, str] = {
    "tool": "Tools",
    "knowledge": "Knowledge",
    "skill": "Skills",
    "agent": "Agents",
    "workflow": "Workflows",
}
MAX_IDS = 100


@dataclass(frozen=True)
class Candidate:
    """One thing the team offers, as the picker lists it."""

    kind: RefKind
    id: str
    label: str
    hint: str | None = None
    needs_approval: bool = False


@dataclass(frozen=True)
class Context:
    """The agent or skill being edited, and what it holds by kind. An agent holds what it is granted; a skill holds
    the tools and knowledge bases it names, and nothing of the other kinds."""

    of: Literal["agent", "skill"]
    id: str
    name: str
    held: Mapping[RefKind, frozenset[str]] = field(default_factory=dict[RefKind, frozenset[str]])


class Item(TypedDict):
    kind: RefKind
    id: str
    label: str
    hint: str | None
    held: bool | None
    adds: str | None
    needsApproval: bool
    disabled: str | None


class Group(TypedDict):
    kind: RefKind
    label: str
    items: list[Item]
    nextCursor: str | None


def _item(c: Candidate, ctx: Context) -> Item:
    holds = ctx.held.get(c.kind)
    held = c.id in holds if holds is not None else None
    adds = f"Adds {c.label} to this agent" if ctx.of == "agent" and held is False else None
    return {
        "kind": c.kind,
        "id": c.id,
        "label": c.label,
        "hint": c.hint,
        "held": held,
        "adds": adds,
        "needsApproval": c.needs_approval,
        "disabled": None,
    }


def matching(offered: Sequence[Candidate], ctx: Context, search: str) -> list[Candidate]:
    """Those of a list held whole in memory (another service's tools or knowledge bases) that hold every word of
    `search`, in the order given, without the record being edited. Skills and agents are searched in the store."""
    words = search.lower().split()
    found: list[Candidate] = []
    for c in offered:
        text = f"{c.label} {c.id} {c.hint or ''}".lower()
        if not (c.kind == ctx.of and c.id == ctx.id) and all(w in text for w in words):
            found.append(c)
    return found


def grouped(pages: Mapping[RefKind, tuple[Sequence[Candidate], str | None]], ctx: Context) -> list[Group]:
    """The picker's groups from one page of each kind and its next cursor; a kind with nothing to show is left out."""
    return [
        {"kind": k, "label": LABELS[k], "items": [_item(c, ctx) for c in pages[k][0]], "nextCursor": pages[k][1]}
        for k in KINDS
        if k in pages and pages[k][0]
    ]


def wanted(ids: Sequence[str]) -> dict[RefKind, list[str]]:
    """What a saved text names (`kind:id` each), by kind, each id once; a token of no known kind is dropped."""
    by_kind: dict[RefKind, list[str]] = {}
    for token in ids[:MAX_IDS]:
        kind, _, ref_id = token.partition(":")
        for k in KINDS:
            if k == kind and ref_id and ref_id not in by_kind.setdefault(k, []):
                by_kind[k].append(ref_id)
    return by_kind


def named(
    offered: Mapping[RefKind, Sequence[Candidate]], ctx: Context, names: Mapping[RefKind, Sequence[str]]
) -> list[Group]:
    """The labels of what a saved text names (`wanted`). One that is not offered, or of a kind not in `offered`, is
    absent from the answer; the page draws it as missing."""
    groups: list[Group] = []
    for k in KINDS:
        by_id = {c.id: c for c in offered.get(k, ())}
        items = [_item(by_id[i], ctx) for i in names.get(k, ()) if i in by_id]
        if items:
            groups.append({"kind": k, "label": LABELS[k], "items": items, "nextCursor": None})
    return groups
