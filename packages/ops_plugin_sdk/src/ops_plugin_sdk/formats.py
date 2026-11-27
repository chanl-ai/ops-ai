"""Checks a tool's input value against what its manifest declares, and writes it into a query so it cannot change the
query: tools-service runs both before any request leaves, and `opsai plugin test` runs the same code.

The template carries its own quotes and a format never adds them, so `Status = '{{status}}'` stays one string literal
whatever the value. `soql_string` escapes what could end the literal; `sosl_term` escapes SOSL's reserved characters,
so a term cannot close `FIND {...}` and add a clause; `jql_string`, `cql_string`, `kql_phrase` and `odata_string` do the
same for a search term in Jira, Confluence, Microsoft Search and OData queries (one function each, which a plugin
written in Python calls too); dates and ids are parsed and written back in one form; an enum's
values are fixed by the manifest, which validate keeps to plain words. A pattern alone cannot make a value safe in a
query, so it is accepted for path segments only, which are URL-encoded."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

from pydantic import JsonValue

from .manifest import InputField

# SOQL's escape sequences (Salesforce SOQL and SOSL reference, "Quoted String Escape Sequences").
SOQL_ESCAPES = {"\\": "\\\\", "'": "\\'", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t", "\b": "\\b", "\f": "\\f"}
# SOSL's reserved characters, each written with a backslash before it inside FIND {...}.
SOSL_RESERVED = set("?&|!{}[]()^~*:\\\"'+-")
# Characters that end a line or a field inside a query string; a search term means the same with a space there.
CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def soql_string(text: str) -> str:
    """A term for a single-quoted SOQL string, by SOQL's escape sequences."""
    return "".join(SOQL_ESCAPES.get(c, c) for c in text)


def jql_string(text: str) -> str:
    """A term for a double-quoted JQL string: a backslash and a double quote each get a backslash before them
    (Atlassian, "Advanced search reference - JQL", reserved characters and quoting), so it cannot close the string."""
    return CONTROL.sub(" ", text).replace("\\", "\\\\").replace('"', '\\"')


def cql_string(text: str) -> str:
    """A term for a double-quoted CQL string, escaped as JQL is (Confluence, "Advanced searching using CQL")."""
    return jql_string(text)


def kql_phrase(text: str) -> str:
    """A term for a double-quoted KQL phrase (Microsoft, "Keyword Query Language (KQL) syntax reference"). KQL has no
    escape for a quote inside a phrase, so a double quote becomes a space; inside the phrase AND, OR, NEAR and
    property:value are read as words. SharePoint's search REST API takes the phrase inside a single-quoted
    querytext='...' literal, so a single quote is doubled there, as that literal requires."""
    return CONTROL.sub(" ", text).replace('"', " ").replace("'", "''")


def odata_string(text: str) -> str:
    """A term for a single-quoted OData string literal: a single quote is doubled (OData 4.01 URL conventions, the
    SQUOTE-in-string rule), so the term cannot close the literal and add a clause."""
    return CONTROL.sub(" ", text).replace("'", "''")


# The formats written inside a quoted string, with the quote the template must put round them and how each is escaped.
QUOTED: dict[str, tuple[str, Callable[[str], str]]] = {
    "soql_string": ("'", soql_string),
    "jql_string": ('"', jql_string),
    "cql_string": ('"', cql_string),
    "kql_phrase": ('"', kql_phrase),
    "odata_string": ("'", odata_string),
}
TEXT_FORMATS = (*QUOTED, "sosl_term")

SALESFORCE_ID = re.compile(r"^[a-zA-Z0-9]{15}(?:[a-zA-Z0-9]{3})?$")


class InputRefused(ValueError):
    """A value its input does not allow; the message names the input and what it must be, never echoing a long value."""


def _date_time(value: Any, name: str) -> datetime:
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError as e:
        raise InputRefused(f"{name} must be a date and time, such as 2026-10-01T09:00:00Z; got {text[:40]!r}") from e
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)


def _date(value: Any, name: str) -> date:
    text = str(value)
    try:
        return date.fromisoformat(text)
    except ValueError as e:
        raise InputRefused(f"{name} must be a date, such as 2026-10-01; got {text[:40]!r}") from e


def check(field: InputField, value: Any, name: str) -> Any:
    """`value` as the input allows it (a date parsed, an array's items each checked), or InputRefused."""
    if field.type == "array":
        if not isinstance(value, list):
            raise InputRefused(f"{name} must be a list")
        items: list[Any] = list(value)  # pyright: ignore[reportUnknownArgumentType]
        if len(items) > field.max_items:
            raise InputRefused(f"{name} may hold at most {field.max_items} items")
        item = field.items or InputField()
        return [check(item, v, f"{name}[{i}]") for i, v in enumerate(items)]
    if field.type == "object" and field.properties is not None:
        if not isinstance(value, dict):
            raise InputRefused(f"{name} must be an object")
        given: dict[str, JsonValue] = dict(value)  # pyright: ignore[reportUnknownArgumentType]
        unknown = sorted(set(given) - set(field.properties))
        if unknown:
            raise InputRefused(f"{name} has no field {unknown[0]}")
        return {k: check(field.properties[k], v, f"{name}.{k}") for k, v in given.items()}
    if field.enum is not None and value not in field.enum:
        raise InputRefused(f"{name} must be one of {', '.join(str(e) for e in field.enum)}")
    if field.pattern is not None and not re.fullmatch(field.pattern, str(value)):
        raise InputRefused(f"{name} must match {field.pattern}")
    if field.format == "date-time":
        return _date_time(value, name)
    if field.format == "date":
        return _date(value, name)
    if field.format == "salesforce_id" and not SALESFORCE_ID.match(str(value)):
        raise InputRefused(f"{name} must be a Salesforce id, 15 or 18 letters and digits")
    if field.format in TEXT_FORMATS and not isinstance(value, str):
        raise InputRefused(f"{name} must be text")
    return value


def render(field: InputField, value: Any) -> str:
    """A checked value as text for a query slot."""
    if field.type == "array":
        item = field.items or InputField()
        return ",".join(render(item, v) for v in value)
    if isinstance(value, datetime):
        return f"{value:%Y-%m-%dT%H:%M:%SZ}"
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).lower() if isinstance(value, bool) else str(value)
    if field.format in QUOTED:
        return QUOTED[field.format][1](text)
    if field.format == "sosl_term":
        return "".join(f"\\{c}" if c in SOSL_RESERVED else c for c in text)
    return text
