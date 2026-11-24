"""Every N minutes, hours or days, from a start time, on chosen weekdays, optionally between two times, in a zone:

  {"kind": "every", "every": 15, "unit": "minutes", "start": "07:00", "days": ["mon", ..., "fri"],
   "between": ["07:00", "18:00"], "tz": "Europe/London", "anchor": "2026-11-24"}

Slots count from the start time on the anchor day, which the save writes. Minutes and hours are spaced in real time,
so a clock change neither shortens nor stretches a gap; days are counted in wall time, so a daily 07:30 stays 07:30.
A slot is kept only on a chosen weekday and, when `between` is set, from its first time to its last, both included.
Left out: every 1 hour, from 00:00, every day, all day, UTC."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from typing import ClassVar

from pydantic import JsonValue

from ..kind import InvalidSchedule, Rule
from ..wall_time import DAY_NAMES, DAYS, clock, local_date, wall, zone

UNITS = {"minutes": (timedelta(minutes=1), 1440), "hours": (timedelta(hours=1), 168), "days": (timedelta(days=1), 366)}
# How far a slot search walks before it decides there is none: past the longest interval plus a week of weekdays.
_SEARCH_DAYS = 400
_TIME = r"^\d{1,2}:\d{2}$"


class Every:
    name = "every"
    label = "Every N minutes, hours or days"
    interval_field = "every"
    schema: ClassVar[Rule] = {
        "type": "object",
        "properties": {
            "kind": {"const": "every"},
            "every": {"type": "integer", "minimum": 1},
            "unit": {"enum": list(UNITS)},
            "start": {"type": "string", "pattern": _TIME},
            "days": {"type": "array", "items": {"enum": list(DAYS)}, "minItems": 1, "uniqueItems": True},
            "between": {"type": "array", "items": {"type": "string", "pattern": _TIME}, "minItems": 2, "maxItems": 2},
            "tz": {"type": "string"},
            "anchor": {"type": "string", "format": "date", "readOnly": True},
        },
        "required": ["kind"],
    }

    def check(self, raw: Mapping[str, JsonValue], now: datetime) -> Rule:
        unit = str(raw.get("unit") or "hours")
        if unit not in UNITS:
            raise InvalidSchedule(f"An interval is in {', '.join(UNITS)}, not {unit}.", field="unit")
        every_raw = 1 if raw.get("every") is None else raw.get("every")
        if not isinstance(every_raw, int | str) or not str(every_raw).isdigit():
            raise InvalidSchedule(f"{every_raw} is not a whole number.", field="every")
        every, most = int(every_raw), UNITS[unit][1]
        if not 1 <= every <= most:
            raise InvalidSchedule(f"Every is 1 to {most} {unit}.", field="every")
        start = str(raw.get("start") or "00:00")
        clock(start, field="start")
        days_raw = raw.get("days")
        days = list(DAYS) if days_raw is None else [str(d).lower()[:3] for d in _listed(days_raw, "days")]
        if not days or any(d not in DAYS for d in days):
            raise InvalidSchedule("Choose at least one weekday.", field="days")
        tz = str(raw.get("tz") or "UTC")
        zone(tz)
        out: Rule = {"kind": self.name, "every": every, "unit": unit, "start": start}
        out["days"] = [d for d in DAYS if d in days]
        if (between_raw := raw.get("between")) is not None:
            between = [str(t) for t in _listed(between_raw, "between")]
            if unit == "days":
                raise InvalidSchedule("Set hours apply to minutes and hours, not days.", field="between")
            if len(between) != 2:
                raise InvalidSchedule("Between takes a first and a last time.", field="between")
            first, last = (clock(t, field="between") for t in between)
            if last <= first:
                raise InvalidSchedule(f"{between[1]} is not after {between[0]}.", field="between")
            out["between"] = list(between)
        out["tz"] = tz
        out["anchor"] = local_date(now, zone(tz)).isoformat()
        return out

    def last_slot(self, rule: Mapping[str, JsonValue], now: datetime) -> datetime | None:
        r = _Parts(rule)
        day = local_date(now, r.tz)
        if r.unit == "days":
            if day < r.anchor:
                return None
            k = (day - r.anchor).days // r.every
            for i in range(k, max(-1, k - _SEARCH_DAYS), -1):
                d = r.anchor + timedelta(days=i * r.every)
                if r.on(d) and (slot := wall(d, r.start, r.tz)) <= now:
                    return slot
            return None
        for _ in range(_SEARCH_DAYS):
            if day < r.anchor - timedelta(days=1):
                return None
            if r.on(day):
                lo, hi = r.window(day)
                top = min(now, hi)
                if top >= max(lo, r.origin):
                    slot = r.origin + r.step * ((top - r.origin) // r.step)
                    if slot >= lo:
                        return slot
            day -= timedelta(days=1)
        return None

    def next_slots(self, rule: Mapping[str, JsonValue], after: datetime, n: int) -> list[datetime]:
        r = _Parts(rule)
        out: list[datetime] = []
        day = max(local_date(after, r.tz), r.anchor)
        if r.unit == "days":
            k = (day - r.anchor).days // r.every
            for i in range(k, k + _SEARCH_DAYS + n):
                d = r.anchor + timedelta(days=i * r.every)
                if r.on(d) and (slot := wall(d, r.start, r.tz)) > after:
                    out.append(slot)
                    if len(out) == n:
                        break
            return out
        for _ in range(_SEARCH_DAYS + n):
            if r.on(day):
                lo, hi = r.window(day)
                bottom = max(lo, r.origin)
                k = (after - r.origin) // r.step + 1 if after >= bottom else -((r.origin - bottom) // r.step)
                slot = r.origin + r.step * k
                while slot <= hi and len(out) < n:
                    out.append(slot)
                    slot += r.step
                if len(out) == n:
                    break
            day += timedelta(days=1)
        return out

    def words(self, rule: Mapping[str, JsonValue]) -> str:
        every, unit = int(str(rule.get("every") or 1)), str(rule.get("unit") or "hours")
        start = str(rule.get("start") or "00:00")
        head = f"Every {unit[:-1]}" if every == 1 else f"Every {every} {unit}"
        parts = [f"{head} {'at' if unit == 'days' else 'from'} {start}"]
        days = [str(d) for d in _listed(rule.get("days") or list(DAYS), "days")]
        if len(days) < len(DAYS):
            parts.append(_day_words(days))
        if between := rule.get("between"):
            first, last = (str(t) for t in _listed(between, "between"))
            parts.append(f"between {first} and {last}")
        parts.append(str(rule.get("tz") or "UTC"))
        return ", ".join(parts)


class _Parts:
    """A stored rule's parts, read once per call."""

    def __init__(self, rule: Mapping[str, JsonValue]) -> None:
        self.every = int(str(rule.get("every") or 1))
        self.unit = str(rule.get("unit") or "hours")
        self.step = UNITS[self.unit][0] * self.every
        self.tz = zone(str(rule.get("tz") or "UTC"))
        self.start = clock(str(rule.get("start") or "00:00"), field="start")
        self.days = {DAYS.index(str(d)) for d in _listed(rule.get("days") or list(DAYS), "days")}
        between = rule.get("between")
        self.between: tuple[time, time] | None = None
        if between:
            first, last = (clock(str(t), field="between") for t in _listed(between, "between"))
            self.between = (first, last)
        self.anchor = date.fromisoformat(str(rule.get("anchor") or "1970-01-01"))
        self.origin = wall(self.anchor, self.start, self.tz)

    def on(self, day: date) -> bool:
        return day.weekday() in self.days

    def window(self, day: date) -> tuple[datetime, datetime]:
        """The first and last instants of `day` a slot may take, both included."""
        if self.between is not None:
            return wall(day, self.between[0], self.tz), wall(day, self.between[1], self.tz)
        nxt = wall(day + timedelta(days=1), time(0), self.tz)
        return wall(day, time(0), self.tz), nxt - timedelta(microseconds=1)


def _listed(value: JsonValue, field: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise InvalidSchedule(f"{field} is a list.", field=field)
    return value


def _day_words(days: list[str]) -> str:
    idx = sorted(DAYS.index(d) for d in days)
    if len(idx) >= 3 and idx == list(range(idx[0], idx[-1] + 1)):
        return f"{DAY_NAMES[idx[0]]} to {DAY_NAMES[idx[-1]]}"
    names = [DAY_NAMES[i] for i in idx]
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"
