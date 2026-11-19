"""The one schedule rule: whether something run on a schedule is due now. Every service's background loop asks it,
so "daily at 02:00" means the same everywhere; after v1 the shared job runner's schedules take its place with the same
shape.

A schedule is one of:

  {"kind": "manual"}                                          never due on its own
  {"kind": "hourly", "every": 1 | 2 | 4 | 6 | 12}             every N hours from the last run
  {"kind": "daily", "time": "02:00", "tz": "Europe/London"}   once a day, at the first beat past the time
  {"kind": "weekly", "day": "mon", "time": "02:00", "tz": ...} once a week, on that day

`tz` is an IANA time zone, UTC when left out. A schedule never run before is due at once, except manual."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import JsonValue

KINDS = ("manual", "hourly", "daily", "weekly")
HOURS = (1, 2, 4, 6, 12)
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class InvalidSchedule(ValueError):
    """A schedule a save refuses; the message names what is wrong."""


@dataclass(frozen=True)
class _Rule:
    """A checked schedule's parts; `checked` writes the ones its kind has, in the stored order."""

    kind: str
    every: int = 1
    time: str = "02:00"
    tz: str = "UTC"
    day: str = "mon"


def _whole(value: JsonValue) -> int:
    # int() as it reads any value: "2" and 2.0 are 2, "x" raises ValueError and a list or object TypeError.
    if isinstance(value, int | float | str):
        return int(value)
    kind = type(value).__name__
    raise TypeError(f"int() argument must be a string, a bytes-like object or a real number, not '{kind}'")


def _rule(schedule: Mapping[str, JsonValue]) -> _Rule:
    kind = str(schedule.get("kind") or "manual")
    if kind not in KINDS:
        raise InvalidSchedule(f"A schedule is {', '.join(KINDS)}, not {kind}.")
    if kind == "manual":
        return _Rule(kind)
    if kind == "hourly":
        every = _whole(schedule.get("every") or 1)
        if every not in HOURS:
            raise InvalidSchedule(f"Every {every} hours is not offered; choose {', '.join(map(str, HOURS))}.")
        return _Rule(kind, every=every)
    at = str(schedule.get("time") or "02:00")
    _clock(at)
    tz = str(schedule.get("tz") or "UTC")
    _zone(tz)
    if kind == "weekly":
        day = str(schedule.get("day") or "mon").lower()[:3]
        if day not in DAYS:
            raise InvalidSchedule(f"A weekly schedule names a day: {', '.join(DAYS)}.")
        return _Rule(kind, time=at, tz=tz, day=day)
    return _Rule(kind, time=at, tz=tz)


def checked(schedule: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """The schedule as stored, or InvalidSchedule naming its problem."""
    r = _rule(schedule)
    if r.kind == "manual":
        return {"kind": "manual"}
    if r.kind == "hourly":
        return {"kind": r.kind, "every": r.every}
    out: dict[str, JsonValue] = {"kind": r.kind, "time": r.time, "tz": r.tz}
    if r.kind == "weekly":
        out["day"] = r.day
    return out


def _clock(at: str) -> time:
    hour, _, minute = at.partition(":")
    try:
        return time(int(hour), int(minute or 0))
    except ValueError as e:
        raise InvalidSchedule(f"{at} is not a time of day (HH:MM).") from e


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise InvalidSchedule(f"{name} is not a time zone.") from e


def last_slot(schedule: Mapping[str, JsonValue], now: datetime) -> datetime | None:
    """The most recent time at or before `now` the schedule asked to run; None for manual."""
    s = _rule(schedule)
    if s.kind == "manual":
        return None
    if s.kind == "hourly":
        hours = s.every
        base = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        return base - timedelta(hours=base.hour % hours)
    zone = _zone(s.tz)
    local = now.astimezone(zone)
    slot = datetime.combine(local.date(), _clock(s.time), tzinfo=zone)
    if slot > local:
        slot -= timedelta(days=1)
    if s.kind == "weekly":
        while DAYS[slot.weekday()] != s.day:
            slot -= timedelta(days=1)
    return slot.astimezone(UTC)


def due(schedule: Mapping[str, JsonValue], last_run: datetime | None, now: datetime) -> bool:
    """Whether a run is due: never run (and not manual), or not run since the schedule's latest slot."""
    slot = last_slot(schedule, now)
    if slot is None:
        return False
    if last_run is None:
        return True
    return last_run < slot


def next_run(schedule: Mapping[str, JsonValue], last_run: datetime | None, now: datetime) -> datetime | None:
    """When the next run is due, for a page to show; None for manual."""
    if _rule(schedule).kind == "manual":
        return None
    if due(schedule, last_run, now):
        return now
    probe = now
    for _ in range(24 * 8):
        probe += timedelta(hours=1)
        if due(schedule, last_run, probe):
            return last_slot(schedule, probe)
    return None
