"""A parameter string can carry paths in braces, `Levy notice: {$.input.record.name}`, so a step writes a readable
line (a case subject) without a step of its own to build it. Validation reads those paths like whole ones."""

from __future__ import annotations

from ops_engine.compiler import resolve
from ops_engine.definition import mappings, referenced_node

SCOPE = {"input": {"record": {"name": "Marcus Bell", "case_no": "NS-1", "amount": 3250.0}}, "nodes": {}}


def test_paths_in_braces_are_filled_in_and_the_rest_is_kept() -> None:
    text = "Levy notice: {$.input.record.name} ({$.input.record.case_no}), {$.input.record.amount}"
    assert resolve(text, SCOPE) == "Levy notice: Marcus Bell (NS-1), 3250.0"


def test_a_missing_value_reads_as_empty_text() -> None:
    assert resolve("Debtor {$.input.record.ssn} on file", SCOPE) == "Debtor  on file"


def test_a_whole_path_still_keeps_its_type() -> None:
    assert resolve("$.input.record.amount", SCOPE) == 3250.0


def test_validation_sees_the_paths_inside_a_text() -> None:
    found = list(mappings({"subject": "Notice {$.nodes.match.out.match.name} / {$.input.notice}"}))
    assert found == ["$.nodes.match.out.match.name", "$.input.notice"]
    assert referenced_node(found[0]) == "match"


def test_a_path_falls_back_to_the_next_when_it_reads_nothing() -> None:
    # A step after an optional review reads the reviewer's correction when the review ran, else the read itself.
    scope = {"input": {}, "nodes": {"read": {"out": {"records": [1]}}}}
    assert resolve("$.nodes.check.out.edited ?? $.nodes.read.out.records", scope) == [1]
    checked = scope | {"nodes": {**scope["nodes"], "check": {"out": {"edited": [2]}}}}
    assert resolve("$.nodes.check.out.edited ?? $.nodes.read.out.records", checked) == [2]
    assert list(mappings({"x": "$.nodes.check.out.edited ?? $.input.a"})) == ["$.nodes.check.out.edited", "$.input.a"]
