"""What the model is asked and how its answer is checked against the schema, the same for every caller (c-235)."""

from __future__ import annotations

import json
from typing import Any, cast

import jsonschema

from ops_extract.checks import answer_schema, records_schema

SYSTEM = (
    "You read a document and fill the fields asked for. For each field give its value as the document writes it, "
    "the exact words from the page that contain it (copied, not paraphrased), and the page number. When the document "
    "does not give a field, answer null for its value, quote and page. Answer only with JSON for the schema."
)


def schema_for(fields: list[dict[str, Any]], *, many: bool) -> dict[str, Any]:
    return records_schema(fields) if many else answer_schema(fields)


def user_prompt(
    fields: list[dict[str, Any]],
    texts: dict[int, str],
    *,
    many: bool,
    examples: list[dict[str, Any]] | None = None,
) -> str:
    """The fields wanted, each with its type and description, the corrections people made on earlier documents of
    the kind (c-297), then the document page by page."""
    wanted = "\n".join(
        f"- {f['key']} ({f.get('type') or 'text'}{', required' if f.get('required') else ''})"
        f"{': ' + str(f['description']) if f.get('description') else ''}"
        for f in fields
    )
    document = "\n\n".join(f"Page {n}:\n{t}" for n, t in sorted(texts.items()))
    each = "\n\nThe document may name several; answer one record per one it names, in its order." if many else ""
    return f"Fields:\n{wanted}{each}{taught(examples)}\n\nDocument:\n{document}"


def taught(examples: list[dict[str, Any]] | None) -> str:
    """Corrections people made on earlier documents of this kind, each the field, the line it was printed on and the
    value it should have been, so the model reads the same kind of line the same way; nothing when there are none."""
    if not examples:
        return ""
    lines: list[str] = []
    for e in examples:
        printed = f'printed "{e["line"]}" ' if e.get("line") else ""
        lines.append(f"- {e['field']}: {printed}is {json.dumps(e['value'], ensure_ascii=False)}")
    return (
        "\n\nPeople corrected these fields on earlier documents of this kind; read the same kind of line the same "
        "way:\n" + "\n".join(lines)
    )


def reread(
    fields: list[dict[str, Any]],
    texts: dict[int, str],
    failures: dict[str, tuple[Any, str]],
    examples: list[dict[str, Any]] | None = None,
) -> str:
    """The one targeted re-read (c-296): only the fields that failed a rule, each with what was read and why it
    failed, then the document again."""
    why = "\n".join(f"- {key}: {said!r} {reason}" for key, (said, reason) in failures.items())
    return (
        f"{user_prompt(fields, texts, many=False, examples=examples)}\n\nThese values were read before and failed a "
        "check. "
        f"Read each again from the page, exactly as printed:\n{why}"
    )


def reask(user: str, errors: list[str]) -> str:
    """The one re-ask after an answer that did not match the schema (Instructor's pattern)."""
    return f"{user}\n\nYour last answer did not match the schema:\n" + "\n".join(errors)


def schema_errors(answer: Any, schema: dict[str, Any]) -> list[str]:
    validator = cast(Any, jsonschema.Draft202012Validator(schema))
    return [f"{'/'.join(str(p) for p in e.path) or '(root)'}: {e.message}" for e in validator.iter_errors(answer)][:20]
