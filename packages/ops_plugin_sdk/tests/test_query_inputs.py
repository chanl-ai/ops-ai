"""Paging rules and checked query inputs, by failure mode: a model's value changes the query it is put into (a quote
leaving a SOQL string, SOSL's reserved characters, a date that is not a date, an id that is not an id, a value outside
its list); a manifest lets an unchecked or pattern-only input into a query, or a string slot without its quotes; a
paging rule cannot be followed; nested inputs grow past what a call can carry. Today's plugins, with none of the new
fields, still validate (test_validate.py's good plugin)."""

from __future__ import annotations

import re
import textwrap
from pathlib import Path

import pytest
from test_validate import MANIFEST, plugin

from ops_plugin_sdk.formats import InputRefused, check, render
from ops_plugin_sdk.manifest import InputField
from ops_plugin_sdk.validate import validate

PAGED = """
  - name: find_cases
    title: Find cases
    access: read
    input:
      status: { type: string, enum: [New, Escalated, Closed] }
      since: { type: string, format: date-time, required: false, default: "1970-01-01T00:00:00Z" }
      account_id: { type: string, format: salesforce_id, required: false }
      subject: { type: string, format: soql_string, required: false }
      fields:
        type: array
        required: false
        items: { type: string, enum: [Id, Subject, Status] }
    request:
      method: GET
      path: /query
      query:
        q: >-
          SELECT {{fields}} FROM Case WHERE Status = '{{status}}' AND Subject = '{{subject}}'
          AND LastModifiedDate > {{since}}
      paging: { rule: link, next: nextRecordsUrl }
  - name: list_view
    title: Records in a list view
    access: read
    input:
      list_view: { type: string, pattern: "^[a-zA-Z0-9]{15,18}$" }
    request:
      method: GET
      path: "/ui-api/list-records/{list_view}"
      paging: { rule: token, next: nextPageToken, param: pageToken }
  - name: search_by_fields
    title: Search by fields
    access: read
    input:
      q: { type: string, format: sosl_term }
    request:
      method: GET
      path: /parameterizedSearch
      query: { q: "{{q}}" }
      paging: { rule: offset, limit: 25, items: searchRecords }
"""


def with_tools(extra: str) -> str:
    tools = textwrap.indent(textwrap.dedent(extra).strip("\n"), "  ")
    return MANIFEST.replace("knowledge_sources:", tools + "\nknowledge_sources:")


def problems(tmp_path: Path, extra: str) -> list[str]:
    return [str(p) for p in validate(plugin(tmp_path, with_tools(extra)))[1]]


def field(**kw: object) -> InputField:
    return InputField.model_validate(kw)


def test_a_paged_tool_with_checked_query_inputs_validates(tmp_path: Path) -> None:
    manifest, found = validate(plugin(tmp_path, with_tools(PAGED)))
    assert found == [], [str(p) for p in found]
    assert manifest is not None
    tool = manifest.tool("find_cases")
    assert tool is not None and tool.title == "Find cases"
    assert tool.request is not None and tool.request.paging is not None and tool.request.paging.rule == "link"


def test_a_quote_cannot_leave_a_soql_string() -> None:
    soql = field(type="string", format="soql_string")
    assert render(soql, check(soql, "x' OR Name != '", "subject")) == "x\\' OR Name != \\'"
    assert render(soql, check(soql, "a\\b\nc", "subject")) == "a\\\\b\\nc"


def test_soql_reserved_characters_are_escaped_in_a_search_term() -> None:
    term = field(type="string", format="sosl_term")
    rendered = render(term, check(term, "card} RETURNING Contact(Email)", "q"))
    assert rendered == "card\\} RETURNING Contact\\(Email\\)"
    assert render(term, check(term, "a*b?c-d+e", "q")) == "a\\*b\\?c\\-d\\+e"


@pytest.mark.parametrize(
    ("kw", "value", "said"),
    [
        ({"format": "date-time"}, "yesterday", "since must be a date and time"),
        ({"format": "date-time"}, "2026-10-01T09:00:00Z' OR Id != '", "since must be a date and time"),
        ({"format": "date"}, "2026-13-40", "since must be a date"),
        ({"format": "salesforce_id"}, "500' OR Id != '", "since must be a Salesforce id"),
        ({"enum": ["New", "Escalated"]}, "Escalated' OR Status != '", "since must be one of New, Escalated"),
        ({"pattern": "^[a-z]+$"}, "abc/../x", "since must match ^[a-z]+$"),
    ],
)
def test_a_value_that_is_not_what_its_input_declares_is_refused(kw: dict[str, object], value: str, said: str) -> None:
    with pytest.raises(InputRefused, match=re.escape(said)):
        check(field(type="string", **kw), value, "since")


def test_dates_are_written_back_in_the_form_salesforce_reads() -> None:
    when = field(type="string", format="date-time")
    assert render(when, check(when, "2026-10-01T11:00:00+02:00", "since")) == "2026-10-01T09:00:00Z"
    day = field(type="string", format="date")
    assert render(day, check(day, "2026-10-01", "on")) == "2026-10-01"


def test_an_array_in_a_query_renders_each_checked_item_joined_by_commas() -> None:
    fields = field(type="array", items={"type": "string", "enum": ["Id", "Subject"]})
    assert render(fields, check(fields, ["Id", "Subject"], "fields")) == "Id,Subject"
    with pytest.raises(InputRefused, match="fields\\[1\\] must be one of Id, Subject"):
        check(fields, ["Id", "Email"], "fields")


def test_a_query_input_with_no_list_or_format_is_refused(tmp_path: Path) -> None:
    bad = PAGED.replace("subject: { type: string, format: soql_string, required: false }", "subject: { type: string }")
    assert any("subject is used in a query and needs an enum or a format" in p for p in problems(tmp_path, bad))


def test_a_query_slot_given_only_a_pattern_is_refused(tmp_path: Path) -> None:
    bad = PAGED.replace(
        "subject: { type: string, format: soql_string, required: false }",
        'subject: { type: string, pattern: "^[a-z]+$" }',
    )
    assert any("subject has only a pattern, which is for path segments" in p for p in problems(tmp_path, bad))


def test_a_soql_string_outside_its_quotes_is_refused(tmp_path: Path) -> None:
    bad = PAGED.replace("Subject = '{{subject}}'", "Subject = {{subject}}")
    assert any("{{subject}} is a soql_string and goes between single quotes" in p for p in problems(tmp_path, bad))


def test_an_enum_value_that_could_change_a_query_is_refused(tmp_path: Path) -> None:
    bad = PAGED.replace("enum: [New, Escalated, Closed]", "enum: [New, \"Closed' OR Id != '\"]")
    assert any("enum value Closed' OR Id != ' may hold only letters" in p for p in problems(tmp_path, bad))


def test_a_query_placeholder_naming_no_input_is_refused(tmp_path: Path) -> None:
    bad = PAGED.replace("Status = '{{status}}'", "Status = '{{state}}'")
    assert any("{{state}} in the query names no input" in p for p in problems(tmp_path, bad))


@pytest.mark.parametrize(
    ("old", "new", "said"),
    [
        (
            "paging: { rule: link, next: nextRecordsUrl }",
            "paging: { rule: link }",
            "a link rule names the answer field",
        ),
        (
            "paging: { rule: token, next: nextPageToken, param: pageToken }",
            "paging: { rule: token, next: nextPageToken }",
            "a token rule names the parameter",
        ),
        (
            "paging: { rule: offset, limit: 25, items: searchRecords }",
            "paging: { rule: offset, limit: 25 }",
            "an offset rule names the answer's list",
        ),
    ],
)
def test_a_paging_rule_with_no_field_to_read_is_refused(tmp_path: Path, old: str, new: str, said: str) -> None:
    assert any(said in p for p in problems(tmp_path, PAGED.replace(old, new)))


def test_nested_inputs_past_three_levels_or_fifty_items_are_refused(tmp_path: Path) -> None:
    deep = """
  - name: deep
    access: read
    input:
      a:
        type: object
        properties:
          b:
            type: object
            properties:
              c:
                type: object
                properties:
                  d: { type: object, properties: { e: { type: string } } }
      many: { type: array, max_items: 51, items: { type: string } }
    request: { method: POST, path: /deep, body: "{{a}}" }
"""
    found = problems(tmp_path, deep)
    assert any("a nests past three levels" in p for p in found), found
    assert any("many may hold at most 50 items" in p for p in found), found
