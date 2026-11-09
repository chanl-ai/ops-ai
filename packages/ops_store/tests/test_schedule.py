"""The one schedule rule, by failure mode: a daily schedule run twice in a day or skipped a day, a time zone ignored,
a weekly one run on the wrong day, hourly drifting, a manual schedule running, and a bad schedule saved."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ops_store.schedule import InvalidSchedule, checked, due, next_run


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def test_daily_runs_once_a_day_after_its_time_in_its_own_time_zone() -> None:
    chicago = {"kind": "daily", "time": "02:00", "tz": "America/Chicago"}  # 08:00 UTC in November
    assert not due(chicago, at("2026-11-09T08:30"), at("2026-11-09T20:00")), "already ran today"
    assert not due(chicago, at("2026-11-08T09:00"), at("2026-11-09T07:59")), "not 02:00 in Chicago yet"
    assert due(chicago, at("2026-11-08T09:00"), at("2026-11-09T08:01"))
    assert due(chicago, None, at("2026-11-09T01:00")), "never run is due at once"


def test_weekly_runs_on_its_day() -> None:
    monday = {"kind": "weekly", "day": "mon", "time": "01:00"}
    assert at("2026-11-09T00:00").weekday() == 0
    assert due(monday, at("2026-11-02T01:30"), at("2026-11-09T01:05"))
    assert not due(monday, at("2026-11-09T01:30"), at("2026-11-12T12:00")), "ran this Monday"


def test_hourly_keeps_to_its_every() -> None:
    four = {"kind": "hourly", "every": 4}
    assert not due(four, at("2026-11-09T04:10"), at("2026-11-09T07:59"))
    assert due(four, at("2026-11-09T04:10"), at("2026-11-09T08:00"))
    assert next_run(four, at("2026-11-09T04:10"), at("2026-11-09T05:00")) == at("2026-11-09T08:00")


def test_manual_never_runs_and_a_bad_schedule_is_refused() -> None:
    assert not due({"kind": "manual"}, None, datetime.now(UTC))
    assert next_run({"kind": "manual"}, None, datetime.now(UTC)) is None
    for bad, says in (
        ({"kind": "hourly", "every": 3}, "Every 3 hours"),
        ({"kind": "daily", "time": "25:00"}, "not a time of day"),
        ({"kind": "daily", "tz": "Mars/Olympus"}, "not a time zone"),
        ({"kind": "monthly"}, "not monthly"),
    ):
        with pytest.raises(InvalidSchedule, match=says):
            checked(bad)
    assert checked({"kind": "weekly", "day": "Friday"})["day"] == "fri"
    assert next_run({"kind": "daily", "time": "02:00"}, at("2026-11-09T02:30"), at("2026-11-09T03:00")) == at(
        "2026-11-10T02:00"
    ) + timedelta(0)
