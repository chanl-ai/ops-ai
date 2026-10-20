# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Which of the team's document types a file is (c-249, model first): the model is shown each type's id, name and
description and the file's first pages, and answers one id or unknown with a confidence and a reason. A kind under the
floor, or unknown, goes to a person rather than being read with the wrong fields."""

from __future__ import annotations

from typing import Any

SYSTEM = (
    "You decide which kind of document this is, choosing from the document types listed. Answer the type's id, how "
    "sure you are from 0 to 1, and one sentence saying which words on the page decided it. When no listed type fits, "
    "answer unknown. Answer only with JSON for the schema."
)
UNKNOWN = "unknown"
# The first pages say what a document is; the rest only costs tokens.
MAX_CHARS = 6000


def schema(type_ids: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["typeId", "confidence", "reason"],
        "properties": {
            "typeId": {"enum": [*type_ids, UNKNOWN]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
        },
    }


def prompt(types: list[dict[str, Any]], texts: dict[int, str]) -> str:
    listed = "\n".join(
        f"- {t['id']}: {t['name']}{' - ' + str(t['description']) if t.get('description') else ''}" for t in types
    )
    document = "\n\n".join(f"Page {n}:\n{t}" for n, t in sorted(texts.items()))[:MAX_CHARS]
    return f"Document types:\n{listed}\n\nDocument:\n{document}"


def classification(answer: dict[str, Any], types: list[dict[str, Any]], floor: float) -> dict[str, Any]:
    """The kind, or none: `needsReview` when the model answered unknown or is less sure than the floor."""
    by_id = {str(t["id"]): t for t in types}
    type_id = str(answer.get("typeId") or UNKNOWN)
    confidence = round(float(answer.get("confidence") or 0.0), 3)
    found = by_id.get(type_id)
    return {
        "typeId": type_id if found else None,
        "name": found["name"] if found else None,
        "confidence": confidence if found else None,
        "reason": str(answer.get("reason") or ""),
        "needsReview": found is None or confidence < floor,
        "floor": floor,
    }
