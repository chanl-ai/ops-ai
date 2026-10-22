"""Starting a workflow by hand (c-466), by failure mode: a Request trigger whose input a file step reads publishes
without marking it a file field, so the start form asks for a file id in a text box; a marked field (string, object or
list) is refused anyway; the rule keys on a field's or step's name; a trigger declares no start form, or the wrong one
for its kind; Files offers a form with no file field."""

from __future__ import annotations

from typing import Any

import pytest

from ops_engine import default_registry
from ops_engine.definition import parse, validate
from ops_engine.node_types import TEST_EMAIL_FORM, start_form


def notice(field: dict[str, Any] | None, *, read: str = "$.input.notice") -> dict[str, Any]:
    """A Request trigger whose input `notice` an Extract from file step reads."""
    props = {"notice": field} if field is not None else {}
    return {
        "schemaVersion": 2,
        "id": "wf_notice",
        "name": "Notice",
        "nodes": [
            {
                "id": "start",
                "type": "ops.trigger.request",
                "typeVersion": 1,
                "parameters": {"inputSchema": {"type": "object", "properties": props}},
            },
            {
                "id": "read",
                "type": "ops.ai.extract",
                "typeVersion": 1,
                "parameters": {"file": read, "fields": [{"key": "debtor", "type": "text"}]},
            },
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "parameters": {}},
        ],
        "connections": [
            {"source": {"node": "start", "port": "payload"}, "target": {"node": "read", "port": "in"}},
            *(
                {"source": {"node": "read", "port": p}, "target": {"node": "done", "port": "in"}}
                for p in ("ok", "review", "unreadable", "error")
            ),
        ],
    }


def codes(d: dict[str, Any]) -> set[str]:
    return {c["code"] for c in validate(parse(d), default_registry())}


@pytest.mark.parametrize(
    "field",
    [
        {"type": "string", "title": "Notice"},  # the staging id box
        {"type": "object"},
        None,  # read but not declared at all
    ],
)
def test_a_file_read_from_an_unmarked_input_is_refused(field: dict[str, Any] | None) -> None:
    assert "file_input_unmarked" in codes(notice(field))


def test_the_refusal_names_the_field_for_a_person() -> None:
    found = list(validate(parse(notice({"type": "string", "title": "Notice"})), default_registry()))
    check = next(c for c in found if c["code"] == "file_input_unmarked")
    assert check["node"] == "start" and check["field"] == "inputSchema"
    assert "Notice" in check["message"]


@pytest.mark.parametrize(
    ("field", "read"),
    [
        ({"type": "string", "format": "file"}, "$.input.notice"),
        ({"type": "object", "properties": {"fileId": {"type": "string"}}}, "$.input.notice.fileId"),
        ({"type": "object", "format": "file"}, "$.input.notice.fileId"),
    ],
)
def test_a_marked_file_field_publishes(field: dict[str, Any], read: str) -> None:
    assert "file_input_unmarked" not in codes(notice(field, read=read))


def test_the_rule_reads_the_step_types_not_names() -> None:
    # An input named fileId that no file step reads is any text; a file step reading another step's output is fine.
    d = notice({"type": "string"}, read="$.nodes.start.out.notice")
    d["nodes"][0]["parameters"]["inputSchema"]["properties"]["fileId"] = {"type": "string"}
    assert "file_input_unmarked" not in codes(d)


def test_each_trigger_kind_declares_its_start_form() -> None:
    reg = default_registry()
    request = start_form(notice({"type": "string", "format": "file", "title": "Notice"}), reg)
    assert request is not None and request["kind"] == "form" and request["via"] == "form"
    assert request["schema"]["properties"]["notice"]["format"] == "file" and request["takesFiles"] is True
    email = start_form(
        {"nodes": [{"id": "t", "type": "ops.trigger.email", "typeVersion": 1, "parameters": {"mailbox": ""}}]}, reg
    )
    assert email is not None and email["kind"] == "email" and email["via"] == "test email"
    assert email["schema"] == dict(TEST_EMAIL_FORM) and email["takesFiles"] is True
    event = {"nodes": [{"id": "t", "type": "ops.trigger.event", "typeVersion": 1, "parameters": {"event": "x.y"}}]}
    assert start_form(event, reg) is None


def test_a_form_without_a_file_field_takes_no_file() -> None:
    form = start_form(notice({"type": "string", "title": "Notice"}), default_registry())
    assert form is not None and form["takesFiles"] is False


def test_an_email_trigger_with_no_mailbox_saves() -> None:
    d = notice({"type": "string", "format": "file"})
    d["nodes"][0] = {"id": "start", "type": "ops.trigger.email", "typeVersion": 1, "parameters": {}}
    d["connections"][0]["source"]["port"] = "payload"
    assert "invalid_parameter" not in codes(d)
