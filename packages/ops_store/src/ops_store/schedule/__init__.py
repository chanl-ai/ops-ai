"""The one schedule rule: when something run on a schedule is due. Every service's background loop asks it, so "daily
at 02:00" means the same everywhere; after v1 the shared job runner's schedules take its place with the same shape.

A rule is `{"kind": <name>, ...the kind's own fields}`. What each kind means lives in its module under `kinds/`;
`ScheduleKinds` holds the kinds and is the only thing callers ask, so the clock and the routes never read a rule's
fields. The functions below (`due`, `last_slot`, `next_run`, `next_slots`) read any registered kind; `checked`, which
knowledge sources save through, accepts only the kinds they have always stored, so a source cannot be set to sync every
minute. A rule never run before is due at once, except manual; a clock that must wait for the next slot instead keeps
that rule itself."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from itertools import pairwise

from pydantic import JsonValue

from .kind import InvalidSchedule, Rule, RuleKind, UnknownKind
from .kinds.every import Every
from .kinds.legacy import Daily, Hourly, Manual, Weekly

__all__ = [
    "InvalidSchedule",
    "Rule",
    "RuleKind",
    "ScheduleKinds",
    "UnknownKind",
    "checked",
    "default_kinds",
    "due",
    "last_slot",
    "next_run",
    "next_slots",
]

# The floor check looks this far ahead for the two closest slots.
_FLOOR_LOOKAHEAD = timedelta(days=7)
_FLOOR_SLOTS = 500


class ScheduleKinds:
    """The registered rule kinds, built like the workflow step-type registry: a duplicate name or a schema that does not
    describe its own kind is refused when it is registered, not when a tick first reads it."""

    def __init__(self, kinds: Iterable[RuleKind] = ()) -> None:
        self._kinds: dict[str, RuleKind] = {}
        for k in kinds:
            self.register(k)

    def register(self, kind: RuleKind) -> None:
        if kind.name in self._kinds:
            raise ValueError(f"The schedule kind {kind.name} is already registered")
        props = kind.schema.get("properties")
        named = isinstance(props, Mapping) and props.get("kind") == {"const": kind.name}
        if kind.schema.get("type") != "object" or not named:
            raise ValueError(f"The schedule kind {kind.name} has a schema that does not name it as its kind")
        self._kinds[kind.name] = kind

    def get(self, name: str) -> RuleKind:
        found = self._kinds.get(name)
        if found is None:
            raise UnknownKind(name, list(self._kinds))
        return found

    def all(self) -> list[RuleKind]:
        return list(self._kinds.values())

    def of(self, rule: Mapping[str, JsonValue]) -> RuleKind:
        return self.get(str(rule.get("kind") or "manual"))

    def checked(self, raw: Mapping[str, JsonValue], now: datetime, floor: timedelta) -> Rule:
        """The rule as stored, or InvalidSchedule naming the field: the kind's own check, then the floor, which holds
        for every kind: no two slots in the coming week closer than `floor`."""
        kind = self.of(raw)
        rule = kind.check(raw, now)
        slots = [s for s in kind.next_slots(rule, now, _FLOOR_SLOTS) if s <= now + _FLOOR_LOOKAHEAD]
        gaps = [b - a for a, b in pairwise(slots)]
        if gaps and (shortest := min(gaps)) < floor:
            raise InvalidSchedule(
                f"Runs {_span(shortest)} apart; the shortest interval here is {_span(floor)}.", kind.interval_field
            )
        return rule

    def last_slot(self, rule: Mapping[str, JsonValue], now: datetime) -> datetime | None:
        return self.of(rule).last_slot(rule, now)

    def next_slots(self, rule: Mapping[str, JsonValue], after: datetime, n: int) -> list[datetime]:
        return self.of(rule).next_slots(rule, after, n)

    def words(self, rule: Mapping[str, JsonValue]) -> str:
        return self.of(rule).words(rule)


def _span(gap: timedelta) -> str:
    minutes = int(gap.total_seconds() // 60)
    if minutes % 60 == 0 and minutes >= 60:
        return f"{minutes // 60} hours" if minutes > 60 else "1 hour"
    return f"{minutes} minutes" if minutes != 1 else "1 minute"


def default_kinds() -> ScheduleKinds:
    """The built-in kinds. A new kind is a module under `kinds/` and one entry here."""
    return ScheduleKinds([Manual(), Hourly(), Daily(), Weekly(), Every()])


_KINDS = default_kinds()
# What a knowledge source may store: the kinds it has always had.
_SOURCE_KINDS = ScheduleKinds([Manual(), Hourly(), Daily(), Weekly()])


def checked(schedule: Mapping[str, JsonValue]) -> Rule:
    """A knowledge source's schedule as stored, or InvalidSchedule naming its problem."""
    return _SOURCE_KINDS.of(schedule).check(schedule, datetime.now(UTC))


def last_slot(schedule: Mapping[str, JsonValue], now: datetime) -> datetime | None:
    """The most recent time at or before `now` the schedule asked to run; None for manual."""
    return _KINDS.last_slot(schedule, now)


def next_slots(schedule: Mapping[str, JsonValue], after: datetime, n: int) -> list[datetime]:
    """Up to `n` slots strictly after `after`."""
    return _KINDS.next_slots(schedule, after, n)


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
    if due(schedule, last_run, now):
        return now
    upcoming = next_slots(schedule, now, 1)
    return upcoming[0] if upcoming else None
