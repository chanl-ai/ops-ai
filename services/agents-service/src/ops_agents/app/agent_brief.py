"""An agent written as a brief: purpose, goal, how to answer, never rules and success checks, in place of one block
of instructions. A save that carries a brief stores it and writes the version's `role` and `instructions` from it, so
lists, the review and evals keep reading the prompt the agent runs on. A version with no `promptMode` was saved
before the brief and is served exactly as it was: nothing here changes it unless a save names the brief or the mode.

Pure functions over the stored spec; they read no directory and no `Runtime`.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from pydantic import ValidationError

from ops_agent_kernel.prompt_writer import Brief, Patterns, head, section_problem, tail
from ops_agent_kernel.types import NEVER_HEADING
from ops_contracts.skill_run import REF_TOKEN, Ref
from ops_service_kit.errors import Unprocessable, ValidationFailed
from ops_service_kit.http import Json
from ops_service_kit.narrow import json_list, json_object

from .instruction_sections import SectionList, default_list, headings, menu_labels, never_label
from .skill_content import Position, Problem

PromptMode = Literal["brief", "full"]
ROLE_MAX = 400


class Uses(TypedDict):
    """How many of each kind the agent holds, for the page's one-line summary."""

    tools: int
    knowledgeBases: int
    skills: int
    agents: int
    workflows: int


def brief_of(spec: Json) -> Brief | None:
    """The brief a version stores; None on a version saved before the brief."""
    stored = spec.get("brief")
    return Brief.model_validate(stored) if stored else None


def brief_view(spec: Json) -> Brief:
    """The brief to start from: the stored one, else the version's role as the purpose and its whole instructions as
    how to answer. Nothing is split out of the old text."""
    return brief_of(spec) or Brief(
        purpose=str(spec.get("role") or spec.get("name") or "")[:ROLE_MAX],
        how_to_answer=str(spec.get("instructions") or ""),
    )


def mode_of(spec: Json) -> PromptMode | None:
    mode = spec.get("promptMode")
    return mode if mode in ("brief", "full") else None


def never_of(spec: Json) -> list[str]:
    """The never rules a turn is given last, in both prompt modes; none on a version without a brief."""
    brief = brief_of(spec) if mode_of(spec) is not None else None
    return list(brief.never) if brief is not None else []


def never_heading_of(spec: Json) -> str:
    """The heading the version's never rules are written under, as the list named it when the brief was saved."""
    return str(spec.get("neverHeading") or NEVER_HEADING)


def prompt_view(spec: Json) -> str:
    """The agent's own prompt as the model reads it, with each mention as the name the model knows it under: the
    stored instructions, then the never rules last. The platform rules, the skill lists and a running step are placed
    by the turn and are not part of it."""
    text = str(spec.get("instructions") or "") or f"You are {spec.get('name')}. {spec.get('role') or ''}".strip()
    if mode_of(spec) is None:
        return text
    never = [rendered(rule, spec) for rule in never_of(spec)]
    return "\n\n".join(p for p in (rendered(text, spec), tail(None, never, never_heading_of(spec))) if p)


def patterns_of(spec: Json) -> Patterns:
    stored = spec.get("patterns")
    return Patterns.model_validate(stored) if stored else Patterns()


def uses_of(spec: Json) -> Uses:
    granted = [str(t) for t in json_list(spec.get("toolIds"))]
    agents = sum(t.startswith("agent:") for t in granted)
    workflows = sum(t.startswith("workflow:") for t in granted)
    return {
        "tools": len(granted) - agents - workflows,
        "knowledgeBases": len(json_list(spec.get("collections"))),
        "skills": len(json_list(spec.get("skillPins"))),
        "agents": agents,
        "workflows": workflows,
    }


def patched(
    spec: Json,
    *,
    brief: Brief | None,
    mode: PromptMode | None,
    patterns: Patterns | None,
    writes_prompt: bool,
    listing: SectionList | None = None,
) -> Json:
    """`spec`, already merged with the rest of a save, with the brief, the prompt mode and the patterns the save
    carries. `writes_prompt` says the save also carries `instructions` or `role`. `listing` is the workspace's list
    of sections (the default when None): it checks the brief's sections, names each menu section by its label and
    sets the order the prompt is written in.

    A save that names neither the brief nor the mode leaves a version without a mode untouched. In brief mode the
    role and the instructions are written again on every save, because the prompt starts with the agent's name.

    Raises:
        ValidationFailed: `validation_failed` when the mode is brief and no purpose can be found.
        Unprocessable: `validation_failed` (422) when the brief's sections break a rule `section_problem` names: a
            section the list does not hold, a menu section twice, more of the builder's own than the list allows,
            or a name taken.
        Unprocessable: `brief_owns_prompt` when a save edits the instructions or the role of an agent in brief mode
            without changing the brief or switching to full prompt.
    """
    listing = listing or default_list()
    order = headings(listing)
    if brief is not None:
        if problem := section_problem(brief.sections, order, listing.custom_max):
            raise Unprocessable(problem, code="validation_failed")
        labels = menu_labels(listing)
        brief = brief.model_copy(
            update={"sections": [s.model_copy(update={"name": labels.get(s.kind, s.name)}) for s in brief.sections]}
        )
    out = dict(spec)
    if patterns is not None:
        out["patterns"] = patterns.model_dump(by_alias=True)
    was = mode_of(spec)
    now: PromptMode | None = mode or ("brief" if brief is not None else was)
    if now is None:
        return out
    if brief is None and now == "brief":
        try:
            brief = brief_view(spec)
        except ValidationError as exc:
            # The brief of a version without one is read from its role and instructions; either can fail to fit.
            too_long = any(e["type"] == "string_too_long" for e in exc.errors())
            raise ValidationFailed(
                "This agent's instructions are too long to become a brief. Shorten them, or keep the full prompt."
                if too_long
                else "Write the agent's purpose before switching to the brief.",
                code="validation_failed",
            ) from exc
        if writes_prompt and mode is None:
            raise Unprocessable(
                "This agent's prompt is written from its brief. Edit the brief, or switch to full prompt to write "
                "the instructions yourself.",
                code="brief_owns_prompt",
            )
    out["promptMode"] = now
    if brief is not None:
        out["brief"] = brief.model_dump(by_alias=True)
        # Kept only when renamed, so a version saved under the default list stores what it stored before.
        out.pop("neverHeading", None)
        if (label := never_label(listing)) != NEVER_HEADING:
            out["neverHeading"] = label
    if now == "brief" and brief is not None:
        out["role"] = brief.purpose.strip()[:ROLE_MAX]
        out["instructions"] = head(str(out.get("name") or ""), brief, order)
    return out


def _held(spec: Json) -> set[str]:
    """Every reference the agent holds, as the token a text names it by."""
    held: set[str] = set()
    for t in (str(t) for t in json_list(spec.get("toolIds"))):
        kind, sep, ref_id = t.partition(":")
        held.add(f"@{kind}:{ref_id}" if sep and kind in ("agent", "workflow") else f"@tool:{t}")
    held.update(f"@knowledge:{k}" for k in json_list(spec.get("collections")))
    held.update(f"@skill:{json_object(p).get('skillId')}" for p in json_list(spec.get("skillPins")))
    return held


def rendered(text: str, spec: Json) -> str:
    """`text` with each `@kind:id` replaced by the name the model knows the target under: a tool's name, a pinned
    skill's slug, `agent:<id>` or `workflow:<id>`; any other id stays as the id."""
    slugs = {
        str(p.get("skillId")): str(p.get("slug") or p.get("skillId"))
        for p in (json_object(p) for p in json_list(spec.get("skillPins")))
    }

    def name(kind: str, ref_id: str) -> str:
        if kind == "skill":
            return slugs.get(ref_id, ref_id)
        return f"{kind}:{ref_id}" if kind in ("agent", "workflow") else ref_id

    return REF_TOKEN.sub(lambda m: name(m.group(1), m.group(2)), text)


def publish_problems(spec: Json) -> list[Problem]:
    """What stops this version from being published, each with the field it is in: a reference the brief names, or
    the plain prompt of an agent in full prompt mode names, that the agent does not hold. A version saved before the
    brief has none."""
    mode = mode_of(spec)
    if mode is None:
        return []
    held = _held(spec)
    # In brief mode the instructions are written from the fields; in full prompt mode they are the prompt itself, and a
    # full prompt may be saved without a brief.
    texts: list[tuple[Position, str]] = []
    if mode == "full":
        texts.append(({"field": "instructions", "step": None, "index": None}, str(spec.get("instructions") or "")))
    if (brief := brief_of(spec)) is not None:
        texts.append(({"field": "brief.purpose", "step": None, "index": None}, brief.purpose))
        texts.append(({"field": "brief.goal", "step": None, "index": None}, brief.goal))
        texts.append(({"field": "brief.howToAnswer", "step": None, "index": None}, brief.how_to_answer))
        texts.extend(
            ({"field": "brief.handOff", "step": None, "index": i}, rule) for i, rule in enumerate(brief.hand_off)
        )
        texts.append(({"field": "brief.examples", "step": None, "index": None}, brief.examples))
        texts.extend(
            ({"field": "brief.sections", "step": None, "index": i}, s.text) for i, s in enumerate(brief.sections)
        )
        texts.extend(({"field": "brief.never", "step": None, "index": i}, rule) for i, rule in enumerate(brief.never))
    problems: list[Problem] = []
    seen: set[str] = set()
    for position, text in texts:
        for ref in Ref.found_in(text):
            if ref.token in held or ref.token in seen:
                continue
            seen.add(ref.token)
            problems.append(
                {
                    "kind": "missing_reference",
                    "id": f"{ref.kind}:{ref.id}",
                    "position": position,
                    "message": f"The {'prompt' if position['field'] == 'instructions' else 'brief'} mentions {ref.id}, "
                    "which this agent does not have. Add it back or remove the mention.",
                }
            )
    return problems
