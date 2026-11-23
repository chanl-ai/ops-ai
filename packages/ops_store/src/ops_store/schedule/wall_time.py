"""Local wall times to real time, with one rule for clock changes: a time that does not exist (clocks go forward) is
the first minute after the gap, and a time that happens twice (clocks go back) is its first occurrence. This is how
Vixie cron and cronie behave."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .kind import InvalidSchedule

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def zone(name: str, field: str = "tz") -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise InvalidSchedule(f"{name} is not a time zone.", field=field) from e


def clock(at: str, field: str = "time") -> time:
    hour, _, minute = at.partition(":")
    try:
        return time(int(hour), int(minute or 0))
    except ValueError as e:
        raise InvalidSchedule(f"{at} is not a time of day (HH:MM).", field=field) from e


def wall(day: date, at: time, tz: ZoneInfo) -> datetime:
    """The UTC instant the wall clock in `tz` shows `at` on `day`."""
    local = datetime.combine(day, at, tzinfo=tz)  # fold=0: the first of a repeated time
    utc = local.astimezone(UTC)
    if utc.astimezone(tz).replace(tzinfo=None) == local.replace(tzinfo=None):
        return utc
    # In a gap zoneinfo reads the time with the offset before the change, which lands past the gap's end; walk back
    # to the change itself, which is the first minute after the gap.
    probe = utc
    while (probe - timedelta(minutes=1)).astimezone(tz).utcoffset() == utc.astimezone(tz).utcoffset():
        probe -= timedelta(minutes=1)
    return probe


def local_date(instant: datetime, tz: ZoneInfo) -> date:
    return instant.astimezone(tz).date()
