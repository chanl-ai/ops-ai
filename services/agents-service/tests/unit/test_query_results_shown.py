"""A query's records in chat, by failure mode: a query envelope ({totalSize, done, records}) drawn as one record whose
records cell says "2 records" instead of a table of them; and the model's present call refused for how it is most often
written (data with no shape, a table's columns as plain names), so each refusal costs another model call."""

from __future__ import annotations

from typing import Any

from ops_agent_kernel import present
from ops_agents.activities.shaper import shape_part
from tests.unit.test_kernel import SETTINGS

RECORDS = [
    {"Id": "5003000000D8cuJAAR", "CaseNumber": "00044818", "Status": "New"},
    {"Id": "5003000000E1aaaAAA", "CaseNumber": "00044901", "Status": "Escalated"},
]


def test_a_query_envelope_is_drawn_as_a_table_of_its_records() -> None:
    envelope: dict[str, Any] = {"totalSize": 2, "done": True, "records": RECORDS}
    part = shape_part(envelope, part_id="p")
    assert part is not None and part["shape"] == "rows", part
    assert [r["CaseNumber"] for r in part["data"]] == ["00044818", "00044901"]
    assert part["hint"]["title"] == "records"
    # Two lists, or a list beside a nested object, are not one list in an envelope: still a record.
    assert shape_part({"cases": RECORDS, "contacts": RECORDS}, part_id="p")["shape"] == "record"  # type: ignore[index]


def test_present_takes_data_alone_as_a_table_and_plain_column_names() -> None:
    shown, said = present.run({"data": RECORDS}, SETTINGS)
    assert shown is not None and shown["shape"] == "rows", said
    table = {"rows": RECORDS, "columns": ["CaseNumber", "Status"]}
    shown, said = present.run({"kind": "table", "data": table}, SETTINGS)
    assert shown is not None, said
    both, said = present.run({"shape": "rows", "kind": "table", "data": RECORDS}, SETTINGS)
    assert both is None and said == "Pass data with only one of shape, kind, widget or layout.", said
