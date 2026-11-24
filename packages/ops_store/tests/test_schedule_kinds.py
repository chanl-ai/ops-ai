"""Schedule rule kinds, by failure mode: a wall time that drifts or doubles at a clock change, a weekday rule that lands
on the wrong day, a bad rule saved (under the floor, every 0, a start the schema refuses, no day, a window that ends
before it starts, an unknown zone or kind), and a stored weekly rule with a bad day looping for good. The
knowledge-base rule's own failure modes stay in test_schedule.py."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest
from pydantic import JsonValue

from ops_store.schedule import InvalidSchedule, UnknownKind, default_kinds, due, next_slots

FLOOR = timedelta(minutes=5)


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def test_wall_times_and_weekday_windows_land_on_the_right_instants() -> None:
    kinds = default_kinds()
    now = at("2026-03-01T00:00")
    morning = kinds.checked({"kind": "daily", "time": "07:30", "tz": "Europe/London"}, now, FLOOR)
    night = kinds.checked({"kind": "daily", "time": "01:30", "tz": "Europe/London"}, now, FLOOR)
    every_night = kinds.checked(
        {"kind": "every", "every": 1, "unit": "days", "start": "01:30", "tz": "Europe/London"}, now, FLOOR
    )

    # Autumn: 25 October 2026 the clocks go back at 02:00 BST, so 01:00-02:00 happens twice.
    assert next_slots(morning, at("2026-10-23T23:00"), 3) == [
        at("2026-10-24T06:30"),
        at("2026-10-25T07:30"),
        at("2026-10-26T07:30"),
    ]
    assert next_slots(night, at("2026-10-23T23:00"), 3) == [
        at("2026-10-24T00:30"),
        at("2026-10-25T00:30"),  # the first 01:30, once
        at("2026-10-26T01:30"),
    ]
    # Spring: 29 March 2026 the clocks go forward at 01:00 GMT, so 01:30 does not exist: the first minute after the
    # gap is 02:00 BST, 01:00 UTC, for every kind that works in wall time.
    spring = [at("2026-03-28T01:30"), at("2026-03-29T01:00"), at("2026-03-30T00:30")]
    assert next_slots(night, at("2026-03-27T23:00"), 3) == spring
    assert next_slots(every_night, at("2026-03-27T23:00"), 3) == spring
    assert not due(night, at("2026-03-28T01:30"), at("2026-03-29T00:59"))
    assert due(night, at("2026-03-28T01:30"), at("2026-03-29T01:00"))

    # Minutes and hours keep their spacing in real time through the gap.
    hourly = kinds.checked({"kind": "every", "every": 1, "unit": "hours", "tz": "Europe/London"}, now, FLOOR)
    slots = next_slots(hourly, at("2026-03-28T23:30"), 4)
    assert [b - a for a, b in pairwise(slots)] == [timedelta(hours=1)] * 3

    # Weekdays between set hours skip the weekend.
    rule = kinds.checked(
        {
            "kind": "every",
            "every": 15,
            "unit": "minutes",
            "start": "07:00",
            "days": ["mon", "tue", "wed", "thu", "fri"],
            "between": ["07:00", "18:00"],
            "tz": "America/New_York",
        },
        at("2026-11-16T12:00"),
        FLOOR,
    )
    friday_six_pm = at("2026-11-20T23:00")  # 18:00 EST
    assert next_slots(rule, friday_six_pm, 3) == [
        at("2026-11-23T12:00"),
        at("2026-11-23T12:15"),
        at("2026-11-23T12:30"),
    ]
    assert not due(rule, friday_six_pm, at("2026-11-22T15:00")), "nothing due on Sunday"
    assert (
        kinds.words(rule) == "Every 15 minutes from 07:00, Monday to Friday, between 07:00 and 18:00, America/New_York"
    )


def test_a_bad_rule_is_refused_naming_its_field_and_stored_kinds_still_load() -> None:
    kinds = default_kinds()
    now = at("2026-11-23T10:00")
    cases: list[tuple[dict[str, JsonValue], str]] = [
        ({"kind": "every", "every": 2, "unit": "minutes"}, "every"),
        ({"kind": "every", "every": 15, "unit": "minutes", "days": []}, "days"),
        ({"kind": "every", "every": 15, "unit": "minutes", "between": ["18:00", "07:00"]}, "between"),
        ({"kind": "every", "every": 15, "unit": "minutes", "tz": "Mars/Phobos"}, "tz"),
        ({"kind": "hourly", "every": 3}, "every"),
        ({"kind": "every", "every": 0, "unit": "hours"}, "every"),
        ({"kind": "every", "every": 1, "unit": "hours", "start": "7"}, "start"),
        ({"kind": "daily", "at": "07:30"}, "at"),
        ({"kind": "weekly", "day": "mon", "times": "07:30"}, "times"),
    ]
    for bad, field in cases:
        with pytest.raises(InvalidSchedule) as refused:
            kinds.checked(bad, now, FLOOR)
        assert refused.value.field == field, bad
    with pytest.raises(UnknownKind) as unknown:
        kinds.checked({"kind": "cron", "line": "* * * * *"}, now, FLOOR)
    assert unknown.value.field == "kind"
    assert {"manual", "hourly", "daily", "weekly", "every"} <= set(unknown.value.known)

    for stored in (
        {"kind": "manual"},
        {"kind": "hourly", "every": 1},
        {"kind": "daily", "time": "02:00", "tz": "UTC"},
        {"kind": "weekly", "day": "mon", "time": "02:00", "tz": "UTC"},
    ):
        assert kinds.checked(stored, now, FLOOR) == stored
    every = kinds.checked({"kind": "every", "every": 15, "unit": "minutes", "tz": "Europe/London"}, now, FLOOR)
    assert every["anchor"] == "2026-11-23", "the save writes the anchor day"
    assert kinds.next_slots({"kind": "weekly", "day": "xyz", "time": "02:00"}, now, 3) == [], "a bad stored day ends"
