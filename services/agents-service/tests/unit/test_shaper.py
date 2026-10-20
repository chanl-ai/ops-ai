"""The tool-result shaper (c-055 T004), one test per rule with the case that must not match it: a malformed part
reaching the console, a column silently dropped into a chart, a declared shape forced onto data it does not fit,
and a part that names the tool."""

from __future__ import annotations

from typing import Any

from ops_agents.activities.shaper import MAX_ROWS, shape_part


def part(output: Any, declared: str | None = None) -> dict[str, Any] | None:
    return shape_part(output, part_id="wp_1", declared=declared)


def test_an_array_of_flat_objects_is_rows_and_nested_or_empty_is_not() -> None:
    txns = [{"id": "T1", "date": "2026-10-01", "amount": 12.5, "memo": "Coffee"}]
    assert part(txns) == {"type": "widget", "id": "wp_1", "shape": "rows", "data": txns}
    assert part([]) is None
    assert part([1, 2, 3]) is None


def test_rows_are_capped() -> None:
    found = part([{"n": f"r{i}", "v": "x"} for i in range(MAX_ROWS + 50)])
    assert found is not None and len(found["data"]) == MAX_ROWS
    assert found["hint"] == {"truncatedFrom": MAX_ROWS + 50}, "the console can say rows were cut"
    whole = part([{"n": "r1", "v": "x"}])
    assert whole is not None and "hint" not in whole


def test_a_date_key_and_numeric_keys_is_a_series_and_an_extra_text_key_keeps_rows() -> None:
    by_day = [{"day": "2026-10-01", "opened": 3, "closed": 1}, {"day": "2026-10-02", "opened": 5, "closed": 4}]
    assert part(by_day) == {
        "type": "widget",
        "id": "wp_1",
        "shape": "series",
        "data": {
            "x": ["2026-10-01", "2026-10-02"],
            "series": [{"name": "opened", "y": [3, 5]}, {"name": "closed", "y": [1, 4]}],
        },
        "hint": {"x": "day"},
    }
    with_memo = [{**r, "memo": "x"} for r in by_day]
    found = part(with_memo)
    assert found is not None and found["shape"] == "rows", "no column is dropped into a chart"


def test_an_ordinal_first_column_is_a_series_and_an_unordered_one_is_rows() -> None:
    by_month = [{"month": 1, "total": 10.0}, {"month": 2, "total": 12.0}, {"month": 3, "total": 9.5}]
    found = part(by_month)
    assert found is not None and found["shape"] == "series" and found["data"]["x"] == [1, 2, 3]
    shuffled = [by_month[1], by_month[0], by_month[2]]
    found = part(shuffled)
    assert found is not None and found["shape"] == "rows"


def test_a_value_with_a_label_is_a_metric_and_an_extra_key_is_a_record() -> None:
    assert part({"value": 4200.5, "label": "Balance", "unit": "CAD"}) == {
        "type": "widget",
        "id": "wp_1",
        "shape": "metric",
        "data": {"value": 4200.5, "label": "Balance", "unit": "CAD"},
    }
    found = part({"value": 4200.5, "label": "Balance", "accountId": "CHQ-1"})
    assert found is not None and found["shape"] == "record"
    assert part({"value": "a lot", "label": "Balance"}) == {
        "type": "widget",
        "id": "wp_1",
        "shape": "record",
        "data": {"value": "a lot", "label": "Balance"},
    }


def test_a_flat_object_is_a_record_and_a_nested_one_is_nothing() -> None:
    customer = {"customerId": "CUS-1", "name": "Ada Okafor", "email": "ada@example.com", "vip": True}
    found = part(customer)
    assert found is not None and found["shape"] == "record" and found["data"] == customer
    assert part("done") is None and part(None) is None


# ── Values that are not flat draw as one cell (c-055 T024), one test per rule ──


def test_a_list_of_scalars_joins_into_one_cell() -> None:
    found = part({"id": "CUS-1001", "name": "Marcus Bell", "accountIds": ["CHQ-2219", "SAV-4410"]})
    assert found is not None and found["shape"] == "record"
    assert found["data"]["accountIds"] == "CHQ-2219, SAV-4410"
    assert part([{"id": "T1", "lines": [1, 2]}]) == {
        "type": "widget",
        "id": "wp_1",
        "shape": "rows",
        "data": [{"id": "T1", "lines": "1, 2"}],
    }


def test_a_list_of_objects_or_a_nested_object_becomes_a_count_naming_its_key() -> None:
    accounts: list[dict[str, Any]] = [
        {"id": "CHQ-2219", "balance": 2140.55, "holds": [{"id": "HLD-1", "amount": 100}, {"id": "HLD-2", "amount": 5}]},
        {"id": "SAV-4410", "balance": 18250.0, "holds": []},
    ]
    found = part(accounts)
    assert found is not None and found["shape"] == "rows"
    assert [r["holds"] for r in found["data"]] == ["2 holds", ""]
    assert part([{"id": "C1", "holds": [{"id": "HLD-1"}]}])["data"][0]["holds"] == "1 hold"  # type: ignore[index]
    nested = part({"customerId": "CUS-1", "address": {"city": "Halifax", "line1": "12 Harbour St"}})
    assert nested is not None and nested["data"]["address"] == "1 address"
    assert part({"customerId": "CUS-1", "addresses": [{"city": "Halifax"}]})["data"]["addresses"] == "1 address"  # type: ignore[index]


def test_the_declared_shape_wins_over_a_cell_that_was_not_flat() -> None:
    customer = {"id": "CUS-1001", "name": "Marcus Bell", "accountIds": ["CHQ-2219"]}
    assert part(customer, declared="record")["shape"] == "record"  # type: ignore[index]
    rows: list[dict[str, Any]] = [
        {"id": "CHQ-2219", "balance": 2140.55, "holds": []},
        {"id": "SAV-4410", "balance": 18250.0, "holds": []},
    ]
    assert part(rows, declared="rows")["shape"] == "rows"  # type: ignore[index]


def test_inference_reads_the_flat_columns_and_a_joined_cell_is_never_a_number_or_a_date() -> None:
    # Two numeric columns plus a joined list: the joined column is text, so this is rows, not a series.
    by_day = [{"day": "2026-10-01", "opened": 3, "ids": [1, 2]}, {"day": "2026-10-02", "opened": 5, "ids": [3]}]
    assert part(by_day)["shape"] == "rows"  # type: ignore[index]
    # Without the list the same data is a series over the date.
    assert part([{k: v for k, v in r.items() if k != "ids"} for r in by_day])["shape"] == "series"  # type: ignore[index]


def test_a_single_key_array_envelope_is_read_as_its_list_with_the_key_as_title() -> None:
    found = part({"transactions": [{"id": "T1", "memo": "Coffee"}]})
    assert found is not None and (found["shape"], found["hint"]) == ("rows", {"title": "transactions"})


def test_a_declared_shape_wins_when_the_data_fits_and_falls_back_when_not() -> None:
    by_day = [{"day": "2026-10-01", "opened": 3}, {"day": "2026-10-02", "opened": 5}]
    found = part(by_day, declared="rows")
    assert found is not None and found["shape"] == "rows", "declared rows over an inferred series"
    found = part({"customerId": "CUS-1", "name": "Ada"}, declared="series")
    assert found is not None and found["shape"] == "record", "a declared shape that does not fit falls back"
    found = part({"customerId": "CUS-1"}, declared="decision")
    assert found is not None and found["shape"] == "record", "only the shapes the shaper makes are honoured"


def test_a_part_never_names_the_tool_or_server() -> None:
    found = part([{"id": "T1"}])
    assert found is not None and set(found) <= {"type", "id", "shape", "data", "hint", "schema"}
