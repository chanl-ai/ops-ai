"""What a schedule rule kind answers. The clock, the slot state, catch-up, overlap, the routes and the target handlers
ask a kind only these members and never read a rule's own fields, so a new kind (cron, a business calendar) is one
module and one line in `default_kinds()`.

All times in and out are aware UTC. A kind that works in wall time converts through `wall_time.wall`, so the gap and
repeat rule holds for every kind."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import ClassVar, Protocol

from pydantic import JsonValue

Rule = dict[str, JsonValue]


class InvalidSchedule(ValueError):
    """A schedule a save refuses; the message names what is wrong and `field` the setting it is about."""

    def __init__(self, message: str, field: str = "kind") -> None:
        super().__init__(message)
        self.field = field


class UnknownKind(InvalidSchedule):
    """A rule whose kind no registry holds; `known` lists the kinds that would be accepted."""

    def __init__(self, kind: str, known: Sequence[str]) -> None:
        super().__init__(f"A schedule is {', '.join(known)}, not {kind}.", field="kind")
        self.known = tuple(known)


class RuleKind(Protocol):
    @property
    def name(self) -> str:
        """Stored as rule["kind"]."""
        ...

    @property
    def label(self) -> str: ...

    schema: ClassVar[Rule]  # JSON Schema of the kind's own fields

    @property
    def interval_field(self) -> str:
        """The field a floor refusal names."""
        ...

    def check(self, raw: Mapping[str, JsonValue], now: datetime) -> Rule:
        """The rule as stored, or InvalidSchedule naming the field."""
        ...

    def last_slot(self, rule: Mapping[str, JsonValue], now: datetime) -> datetime | None:
        """The latest slot at or before `now`; None when the rule has none (manual)."""
        ...

    def next_slots(self, rule: Mapping[str, JsonValue], after: datetime, n: int) -> list[datetime]:
        """Up to `n` slots strictly after `after`, in order."""
        ...

    def words(self, rule: Mapping[str, JsonValue]) -> str: ...
