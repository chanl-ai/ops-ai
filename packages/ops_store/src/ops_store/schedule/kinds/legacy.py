"""The kinds knowledge sources have stored since the first schedule rule, kept valid as they are:

  {"kind": "manual"}                                          never due on its own
  {"kind": "hourly", "every": 1 | 2 | 4 | 6 | 12}             every N hours, at whole UTC hours that divide by N
  {"kind": "daily", "time": "02:00", "tz": "Europe/London"}   once a day at the time
  {"kind": "weekly", "day": "mon", "time": "02:00", "tz": ...} once a week, on that day

`tz` is an IANA time zone, UTC when left out. Wall times follow `wall_time.wall` at a clock change."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import ClassVar

from pydantic import JsonValue

from ..kind import InvalidSchedule, Rule
from ..wall_time import DAY_NAMES, DAYS, clock, local_date, wall, zone

HOURS = (1, 2, 4, 6, 12)


def _whole(value: JsonValue, field: str) -> int:
    # As int() reads a value: "2" and 2.0 are 2; anything else is refused naming the field.
    if isinstance(value, int | float | str):
        try:
            return int(value)
        except ValueError as e:
            raise InvalidSchedule(f"{value} is not a whole number.", field=field) from e
    raise InvalidSchedule(f"{field} is a whole number.", field=field)


class Manual:
    name = "manual"
    label = "Only when started by hand"
    interval_field = "kind"
    schema: ClassVar[Rule] = {"type": "object", "properties": {"kind": {"const": "manual"}}, "required": ["kind"]}

    def check(self, raw: Mapping[str, JsonValue], now: datetime) -> Rule:
        return {"kind": "manual"}

    def last_slot(self, rule: Mapping[str, JsonValue], now: datetime) -> datetime | None:
        return None

    def next_slots(self, rule: Mapping[str, JsonValue], after: datetime, n: int) -> list[datetime]:
        return []

    def words(self, rule: Mapping[str, JsonValue]) -> str:
        return "Only when started by hand"


class Hourly:
    name = "hourly"
    label = "Every 1, 2, 4, 6 or 12 hours"
    interval_field = "every"
    schema: ClassVar[Rule] = {
        "type": "object",
        "properties": {"kind": {"const": "hourly"}, "every": {"enum": list(HOURS)}},
        "required": ["kind"],
    }

    def check(self, raw: Mapping[str, JsonValue], now: datetime) -> Rule:
        every = _whole(raw.get("every") or 1, "every")
        if every not in HOURS:
            raise InvalidSchedule(f"Every {every} hours is not offered; choose {', '.join(map(str, HOURS))}.", "every")
        return {"kind": self.name, "every": every}

    def _every(self, rule: Mapping[str, JsonValue]) -> int:
        return _whole(rule.get("every") or 1, "every")

    def _floor(self, rule: Mapping[str, JsonValue], now: datetime) -> datetime:
        base = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        return base - timedelta(hours=base.hour % self._every(rule))

    def last_slot(self, rule: Mapping[str, JsonValue], now: datetime) -> datetime | None:
        return self._floor(rule, now)

    def next_slots(self, rule: Mapping[str, JsonValue], after: datetime, n: int) -> list[datetime]:
        step = timedelta(hours=self._every(rule))
        slot = self._floor(rule, after) + step
        return [slot + step * i for i in range(n)]

    def words(self, rule: Mapping[str, JsonValue]) -> str:
        every = self._every(rule)
        return "Every hour" if every == 1 else f"Every {every} hours"


class Daily:
    name = "daily"
    label = "Once a day at a time"
    interval_field = "time"
    schema: ClassVar[Rule] = {
        "type": "object",
        "properties": {
            "kind": {"const": "daily"},
            "time": {"type": "string", "pattern": r"^\d{1,2}:\d{2}$"},
            "tz": {"type": "string"},
        },
        "required": ["kind"],
    }

    def check(self, raw: Mapping[str, JsonValue], now: datetime) -> Rule:
        at = str(raw.get("time") or "02:00")
        clock(at)
        tz = str(raw.get("tz") or "UTC")
        zone(tz)
        return {"kind": self.name, "time": at, "tz": tz}

    def _on(self, rule: Mapping[str, JsonValue], weekday: int) -> bool:
        return True

    def last_slot(self, rule: Mapping[str, JsonValue], now: datetime) -> datetime | None:
        tz, at = zone(str(rule.get("tz") or "UTC")), clock(str(rule.get("time") or "02:00"))
        day = local_date(now, tz)
        for _ in range(8):
            if self._on(rule, day.weekday()) and (slot := wall(day, at, tz)) <= now:
                return slot
            day -= timedelta(days=1)
        return None

    def next_slots(self, rule: Mapping[str, JsonValue], after: datetime, n: int) -> list[datetime]:
        tz, at = zone(str(rule.get("tz") or "UTC")), clock(str(rule.get("time") or "02:00"))
        day, out = local_date(after, tz), list[datetime]()
        # Bounded: a stored rule whose day matches no weekday gives no slots instead of looping for good.
        for _ in range(8 * n + 8):
            if len(out) == n:
                break
            if self._on(rule, day.weekday()) and (slot := wall(day, at, tz)) > after:
                out.append(slot)
            day += timedelta(days=1)
        return out

    def words(self, rule: Mapping[str, JsonValue]) -> str:
        return f"Every day at {rule.get('time') or '02:00'}, {rule.get('tz') or 'UTC'}"


class Weekly(Daily):
    name = "weekly"
    label = "Once a week on a day"
    schema: ClassVar[Rule] = {
        "type": "object",
        "properties": {
            "kind": {"const": "weekly"},
            "day": {"enum": list(DAYS)},
            "time": {"type": "string", "pattern": r"^\d{1,2}:\d{2}$"},
            "tz": {"type": "string"},
        },
        "required": ["kind"],
    }

    def check(self, raw: Mapping[str, JsonValue], now: datetime) -> Rule:
        out = super().check(raw, now)
        day = str(raw.get("day") or "mon").lower()[:3]
        if day not in DAYS:
            raise InvalidSchedule(f"A weekly schedule names a day: {', '.join(DAYS)}.", field="day")
        return {"kind": self.name, "day": day, "time": out["time"], "tz": out["tz"]}

    def _on(self, rule: Mapping[str, JsonValue], weekday: int) -> bool:
        return DAYS[weekday] == str(rule.get("day") or "mon")

    def words(self, rule: Mapping[str, JsonValue]) -> str:
        day = DAY_NAMES[DAYS.index(str(rule.get("day") or "mon"))]
        return f"Every {day} at {rule.get('time') or '02:00'}, {rule.get('tz') or 'UTC'}"
