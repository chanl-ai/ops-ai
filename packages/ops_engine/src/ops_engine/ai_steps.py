"""Workflow AI steps (c-298): Classify, Summarise, Extract from text and Draft. Each is its own node type, and all four
run one executor over one model call (the agent kernel with no tools, the step's instructions, model alias and an
answer schema; EnginePorts.prompts). A job here only says what its answer looks like, how the model is asked, and
which port an answer leaves by, from the step's settings: no category, field or wording is fixed in code."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, cast

from .ports import PromptPort, PromptRequest

# The ports every Classify step has besides one per category; a category may not take either name.
OTHERWISE = "otherwise"
ERROR = "error"
DEFAULT_FLOOR = 0.6
DEFAULT_WORDS = 120
# A document type field's type, as the answer schema reads it (documents-service DocumentTypeVersionIn.fields).
FIELD_TYPES: dict[str, str] = {
    "text": "string",
    "date": "string",
    "enum": "string",
    "number": "number",
    "money": "number",
}


@dataclass(frozen=True)
class Job:
    schema: Callable[[Mapping[str, Any]], dict[str, Any]]
    instructions: Callable[[Mapping[str, Any]], str]
    # The port an answer leaves by, and the step's output.
    route: Callable[[dict[str, Any], Mapping[str, Any]], tuple[str, dict[str, Any]]]


def _extra(params: Mapping[str, Any]) -> str:
    more = str(params.get("instructions") or "").strip()
    return f"\n\n{more}" if more else ""


def _categories(params: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [cast(dict[str, Any], c) for c in cast(list[Any], params.get("categories") or []) if isinstance(c, dict)]


def _classify_schema(params: Mapping[str, Any]) -> dict[str, Any]:
    names = [str(c["name"]) for c in _categories(params)]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["category", "confidence", "reason"],
        "properties": {
            # "none" lets the model say nothing fits rather than force a category.
            "category": {"type": "string", "enum": [*names, "none"]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
        },
    }


def _classify_instructions(params: Mapping[str, Any]) -> str:
    lines = "\n".join(f"- {c['name']}: {c.get('description') or c['name']}" for c in _categories(params))
    return (
        "Put the text in exactly one of these categories, or none when none fits. Give your confidence from 0 to 1 "
        f"and the reason in one sentence.\n\nCategories:\n{lines}" + _extra(params)
    )


def _classify_route(answer: dict[str, Any], params: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    names = {str(c["name"]) for c in _categories(params)}
    floor = params.get("minConfidence")
    floor = float(floor) if isinstance(floor, int | float) else DEFAULT_FLOOR
    category, confidence = str(answer.get("category")), float(answer.get("confidence") or 0)
    out = {
        "category": category if category in names else None,
        "confidence": confidence,
        "reason": answer.get("reason"),
    }
    # Below the floor the step does not guess: the builder wires otherwise to a person or a default.
    return (category if category in names and confidence >= floor else OTHERWISE), out


def _summary_schema(params: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}},
    }


def _summary_instructions(params: Mapping[str, Any]) -> str:
    words = params.get("maxWords")
    n = int(words) if isinstance(words, int) and words > 0 else DEFAULT_WORDS
    return f"Summarise the text in at most {n} words, keeping names, amounts and dates exactly as written." + _extra(
        params
    )


def fields_schema(fields: list[dict[str, Any]]) -> dict[str, Any]:
    """The answer for Extract from text: each field's value by its key, null when the text does not give it."""
    props: dict[str, Any] = {}
    for f in fields:
        kind: dict[str, Any] = {"type": [FIELD_TYPES.get(str(f.get("type") or "text"), "string"), "null"]}
        if f.get("type") == "enum" and f.get("options"):
            kind["enum"] = [*cast(list[Any], f["options"]), None]
        if f.get("description"):
            kind["description"] = str(f["description"])
        props[str(f["key"])] = kind
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


def _fields(params: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [cast(dict[str, Any], f) for f in cast(list[Any], params.get("fields") or []) if isinstance(f, dict)]


def _extract_instructions(params: Mapping[str, Any]) -> str:
    lines = "\n".join(f"- {f['key']}: {f.get('label') or f['key']}" for f in _fields(params))
    return (
        "Read these fields from the text. Give each value as the text writes it; give null for a field the text does "
        f"not state, never a guess.\n\nFields:\n{lines}" + _extra(params)
    )


def _draft_schema(params: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["subject", "body"],
        "properties": {"subject": {"type": ["string", "null"]}, "body": {"type": "string"}},
    }


def _draft_instructions(params: Mapping[str, Any]) -> str:
    return (
        "Write the draft the instructions ask for, from the text given. It is a draft: a person or a later step sends "
        "it. Give a subject when it is an email, else null." + _extra(params)
    )


def _ok(answer: dict[str, Any], params: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    return "ok", answer


JOBS: dict[str, Job] = {
    "ops.ai.classify": Job(_classify_schema, _classify_instructions, _classify_route),
    "ops.ai.summarise": Job(_summary_schema, _summary_instructions, _ok),
    "ops.ai.extractText": Job(lambda p: fields_schema(_fields(p)), _extract_instructions, _ok),
    "ops.ai.draft": Job(_draft_schema, _draft_instructions, _ok),
}


def message_of(text: Any) -> str:
    """What the model reads: the mapped text as it is, or other values as JSON."""
    return text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, sort_keys=True, default=str)


async def resolve_fields(
    params: Mapping[str, Any], lookup: Callable[[str, int | None], Awaitable[list[dict[str, Any]]]] | None
) -> dict[str, Any]:
    """The step's settings with a named document type's fields in place (Extract from text, c-298): `lookup` reads
    them as whoever runs the step, the run's team in a workflow or the caller's on the route."""
    out = dict(params)
    if (ref := out.get("documentType")) and not out.get("fields"):
        if lookup is None:
            raise RuntimeError("no document types lookup: this host cannot read a document type's fields")
        typed = cast(dict[str, Any], ref)
        out["fields"] = await lookup(str(typed["id"]), cast(int | None, typed.get("version")))
    return out


async def run(
    type_id: str, params: Mapping[str, Any], prompts: PromptPort, *, turn_id: str, run_id: str | None = None
) -> tuple[str, dict[str, Any]]:
    """One AI step's answer and the port it leaves by: the workflow step (compiler.ai_prompt) and agents-service's
    AI step route both run it, so a step and an outside caller get the same answer. An answer outside the schema, or
    a host that refuses the call, leaves by error; a model out of reach is raised by the port."""
    job = JOBS[type_id]
    result = await prompts.prompt(
        PromptRequest(
            instructions=job.instructions(params),
            message=message_of(params.get("text")),
            turn_id=turn_id,
            output_schema=job.schema(params),
            model_alias=cast(str | None, params.get("model")) or None,
            run_id=run_id,
        )
    )
    if not result.ok:
        return ERROR, {"error": result.error or result.text, "code": result.code}
    return job.route(cast(dict[str, Any], result.output or {}), params)
