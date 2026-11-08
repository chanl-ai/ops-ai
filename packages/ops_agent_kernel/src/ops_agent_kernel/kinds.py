"""Widget kinds: generic, schema-driven widgets an agent shows with `present {kind, data}`, the same in any
industry. The industry is in the data and its labels, never in the kind: a tracker follows an order, a claim, an
application or a shipment alike.

Each kind is one JSON Schema. A `present` call fills the kind through the binder every template uses (`layout.fill`),
with a binding generated from the schema, so a kind passes the same catalogue, closed-field and size checks as any
layout. A builder's template can place a kind as a node and `$bind` its fields. Every schema closes its objects
(`additionalProperties: false`) and has no field for a link, script, HTML or image source: a button, slot or form only
sends a message back to the agent. `apps/console/src/lib/widgets/kinds.schema.json` is this module's `SCHEMAS`, written
by `python -m ops_agent_kernel.kinds --write` and compared in the kernel's tests.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

MAX_ITEMS = 50

TEXT: dict[str, Any] = {"type": "string", "minLength": 1, "maxLength": 2000}
CELL: dict[str, Any] = {"type": ["string", "number", "boolean", "null"]}
TONE: dict[str, Any] = {"enum": ["neutral", "info", "success", "warning", "danger"]}
STATE: dict[str, Any] = {"enum": ["pending", "active", "done", "failed"]}
# A file the console opens in its own Files panel: an id, never a URL.
FILE_ID: dict[str, Any] = {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,64}$"}
# The app a card's data came from, by its id in the team's Apps (`plugin:opsai.salesforce`): the console draws its name
# and logo from the team's own record of it.
APP: dict[str, Any] = {"type": "string", "pattern": "^[a-z]+:[A-Za-z0-9._-]{1,80}$"}
# A record in that app, by its path only. The console opens it on the address the app's account signed in to, so a
# card can never send anyone to a host the model chose: no scheme, no host, no `//`, no query.
OPEN: dict[str, Any] = {
    "type": "object",
    "properties": {"path": {"type": "string", "pattern": "^/(?!/)[A-Za-z0-9/_.~%-]{0,300}$"}, "label": TEXT},
    "required": ["path"],
    "additionalProperties": False,
}


def _obj(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


def _list(item: dict[str, Any], *, least: int = 1, most: int = MAX_ITEMS) -> dict[str, Any]:
    return {"type": "array", "items": item, "minItems": least, "maxItems": most}


# What a button sends back as the person's next message; the only thing any kind can do.
ACTION = _obj({"label": TEXT, "reply": TEXT}, ["label", "reply"])
STATUS = _obj({"text": TEXT, "tone": TONE}, ["text"])
# `was`: the value before a change the card reports, drawn as old → new.
PAIRS = _list(_obj({"label": TEXT, "value": CELL, "was": CELL}, ["label", "value"]), least=0)
ROWS = _list({"type": "object", "maxProperties": 20, "additionalProperties": CELL})
STEP = _obj({"label": TEXT, "state": STATE, "detail": TEXT, "at": TEXT}, ["label", "state"])

SCHEMAS: dict[str, dict[str, Any]] = {
    # A figure with its change and recent trend; `goodWhen` says which way is good, so the change is coloured right.
    "metric": _obj(
        {
            "label": TEXT,
            "value": {"type": ["number", "string"]},
            "unit": TEXT,
            "delta": {"type": "number"},
            "deltaLabel": TEXT,
            "goodWhen": {"enum": ["up", "down"]},
            "trend": _list({"type": "number"}, least=2, most=60),
        },
        ["label", "value"],
    ),
    "table": _obj(
        {
            "rows": ROWS,
            "columns": _list(
                _obj(
                    {"key": TEXT, "label": TEXT, "format": {"enum": ["text", "number", "money", "date", "percent"]}},
                    ["key"],
                ),
                most=20,
            ),
        },
        ["rows"],
    ),
    "chart": _obj(
        {
            "rows": _list({"type": "object", "maxProperties": 20, "additionalProperties": CELL}, least=2),
            "x": TEXT,
            "y": _list(TEXT, most=5),
            "kind": {"enum": ["line", "bar", "area"]},
        },
        ["rows", "x", "y"],
    ),
    "timeline": _obj(
        {
            "title": TEXT,
            "events": _list(_obj({"at": TEXT, "title": TEXT, "detail": TEXT, "tone": TONE}, ["at", "title"])),
        },
        ["events"],
    ),
    # The steps of one process: an order, a claim, an application, a shipment.
    "tracker": _obj({"title": TEXT, "reference": TEXT, "steps": _list(STEP, most=20)}, ["steps"]),
    # One thing with its fields: a person, customer, patient, product or account; after a write, what changed.
    "entity": _obj(
        {
            "title": TEXT,
            "subtitle": TEXT,
            "category": TEXT,
            "status": STATUS,
            "fields": PAIRS,
            "actions": _list(ACTION, least=0, most=4),
            "app": APP,
            "open": OPEN,
        },
        ["title", "fields"],
    ),
    # What to know before a meeting or a call: who and when, then a few sections, each with a count and its top items.
    "brief": _obj(
        {
            "title": TEXT,
            "when": TEXT,
            "who": TEXT,
            "sections": _list(
                _obj(
                    {
                        "title": TEXT,
                        "count": {"type": "integer", "minimum": 0},
                        "items": _list(_obj({"text": TEXT, "detail": TEXT}, ["text"]), least=0, most=8),
                        "note": TEXT,
                    },
                    ["title", "items"],
                ),
                most=6,
            ),
            "app": APP,
            "open": OPEN,
        },
        ["title", "sections"],
    ),
    "comparison": _obj(
        {
            "title": TEXT,
            "attributes": _list(TEXT, most=20),
            "options": _list(
                _obj(
                    {
                        "name": TEXT,
                        "badge": TEXT,
                        "recommended": {"type": "boolean"},
                        "values": {"type": "object", "maxProperties": 20, "additionalProperties": CELL},
                        "action": ACTION,
                    },
                    ["name", "values"],
                ),
                least=2,
                most=6,
            ),
        },
        ["attributes", "options"],
    ),
    "checklist": _obj(
        {
            "title": TEXT,
            "items": _list(_obj({"label": TEXT, "done": {"type": "boolean"}, "detail": TEXT}, ["label", "done"])),
        },
        ["items"],
    ),
    # Fields the person fills; Submit sends the reply text and the answers back as their next message.
    "form": _obj(
        {
            "title": TEXT,
            "fields": _list(
                _obj(
                    {
                        "name": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_]{0,40}$"},
                        "label": TEXT,
                        "type": {"enum": ["text", "textarea", "number", "date", "select", "boolean"]},
                        "options": _list(TEXT, most=20),
                        "required": {"type": "boolean"},
                        "placeholder": TEXT,
                        # The value the field opens with, and why the app refused it when the card comes back.
                        "value": CELL,
                        "error": TEXT,
                    },
                    ["name", "label", "type"],
                ),
                most=12,
            ),
            "submit": ACTION,
            # A second button beside submit (Edit): it sends its reply, like any action.
            "edit": ACTION,
            "subtitle": TEXT,
            # A line beside the buttons: what submitting writes.
            "note": TEXT,
            "app": APP,
        },
        ["fields", "submit"],
    ),
    # A yes-or-no the agent asks before it acts; each answer is a message, never the action itself.
    "confirm": _obj(
        {"title": TEXT, "summary": TEXT, "details": PAIRS, "tone": TONE, "confirm": ACTION, "cancel": ACTION},
        ["title", "confirm"],
    ),
    # The page of a file an answer cites, the passage marked; the console opens the file by id in its Files panel.
    "document": _obj(
        {
            "name": TEXT,
            "page": {"type": "integer", "minimum": 1},
            "pages": {"type": "integer", "minimum": 1},
            "before": TEXT,
            "passage": TEXT,
            "after": TEXT,
            "fileId": FILE_ID,
        },
        ["name", "passage"],
    ),
    "quote": _obj(
        {
            "passage": TEXT,
            "source": TEXT,
            "page": {"type": "integer", "minimum": 1},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "fileId": FILE_ID,
        },
        ["passage", "source"],
    ),
    "plan": _obj(
        {
            "title": TEXT,
            "description": TEXT,
            "steps": _list(_obj({"label": TEXT, "state": STATE, "detail": TEXT}, ["label", "state"]), most=20),
            "action": ACTION,
        },
        ["title", "steps"],
    ),
    "reasoning": _obj(
        {
            "title": TEXT,
            "steps": _list(
                _obj(
                    {
                        "label": TEXT,
                        "detail": TEXT,
                        "state": {"enum": ["done", "active", "pending"]},
                        "results": _list(TEXT, least=0, most=8),
                    },
                    ["label", "state"],
                ),
                most=12,
            ),
        },
        ["steps"],
    ),
    # Times to pick from; picking sends "<reply> <day> <slot>" back, so booking stays the agent's tool call.
    "slots": _obj(
        {
            "title": TEXT,
            "timezone": TEXT,
            "reply": TEXT,
            "days": _list(
                _obj(
                    {
                        "day": TEXT,
                        "slots": _list(
                            _obj({"label": TEXT, "available": {"type": "boolean"}}, ["label", "available"]), most=12
                        ),
                    },
                    ["day", "slots"],
                ),
                most=7,
            ),
        },
        ["title", "reply", "days"],
    ),
    "receipt": _obj(
        {
            "title": TEXT,
            "number": TEXT,
            "date": TEXT,
            "party": TEXT,
            "currency": {"type": "string", "pattern": "^[A-Z]{3}$"},
            "lines": _list(
                _obj(
                    {
                        "label": TEXT,
                        "quantity": {"type": "number"},
                        "unitPrice": {"type": "number"},
                        "amount": {"type": "number"},
                    },
                    ["label", "amount"],
                )
            ),
            "subtotal": {"type": "number"},
            "tax": {"type": "number"},
            "total": {"type": "number"},
            "status": STATUS,
        },
        ["title", "currency", "lines", "total"],
    ),
    # Phone and email are shown as text to copy; a kind carries no link.
    "contact": _obj(
        {
            "name": TEXT,
            "role": TEXT,
            "organisation": TEXT,
            "phone": TEXT,
            "email": TEXT,
            "address": TEXT,
            "hours": TEXT,
            "actions": _list(ACTION, least=0, most=4),
        },
        ["name"],
    ),
}

KINDS = tuple(SCHEMAS)
# Kinds that were catalogue primitives before the widget kinds and keep their own field checks in `layout.CATALOGUE`.
PRIMITIVES = ("metric", "table", "chart")


def template(kind: str) -> dict[str, Any]:
    """The binding a `present {kind, data}` call fills: the kind's node with each top-level field bound to the same
    field of the data, so the existing binder (`layout.fill`) checks and fills it."""
    return {"type": kind, **{name: {"$bind": f"/{name}"} for name in SCHEMAS[kind]["properties"]}}


def describe() -> str:
    """One line per kind for the present tool's description: its fields, required ones marked."""
    out: list[str] = []
    for kind, schema in SCHEMAS.items():
        required = set(schema["required"])
        fields = ", ".join(f"{name}{'*' if name in required else ''}" for name in schema["properties"])
        out.append(f"{kind}({fields})")
    return "; ".join(out)


CONSOLE_COPY = (
    Path(__file__).resolve().parents[4] / "apps" / "console" / "src" / "lib" / "widgets" / "kinds.schema.json"
)


def render() -> str:
    return json.dumps(SCHEMAS, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    if "--write" in sys.argv:
        CONSOLE_COPY.write_text(render())
    else:
        sys.stdout.write(render())
