"""Ports with a conformance suite: the operations whose correctness rests on a database guarantee.

A service's repository implements a port (often through a thin adapter in its tests) and runs the port's suite on
every backend in `backends.BACKENDS`. Methods answer with values rather than raising, so a suite reads the same
whatever exception types the implementation uses inside.
"""

from __future__ import annotations

from typing import Any, Protocol

from .guarantees import Repository


class LeasePort(Repository, Protocol):
    """Exclusive ownership of a key with a generation that grows on every new owner (CAS by generation)."""

    # Seconds a lease lives without renewal.
    ttl: float

    async def try_acquire(self, key: str, holder: str) -> int | None:
        """The new generation, or None while another holder's lease is live."""
        ...

    async def write_fenced(self, key: str, generation: int) -> bool:
        """A write that lands only while `generation` still owns `key`; False when a newer owner took it."""
        ...


class TimerClaimPort(Repository, Protocol):
    """A due timer is claimed by exactly one of any number of concurrent pollers."""

    async def arm(self, timer_id: str, generation: int) -> None: ...

    async def claim(self, timer_id: str, generation: int) -> bool:
        """True for the one caller that claimed it; False for every other, and for any later claim."""
        ...


class AuditPort(Repository, Protocol):
    """A change and its audit entry land together or not at all."""

    async def apply(self, entity_id: str, value: str, entry: dict[str, Any] | None) -> None:
        """Sets the value and records the entry in one unit; an entry the store refuses (None) fails both."""
        ...

    async def value(self, entity_id: str) -> str | None: ...

    async def entries(self, entity_id: str) -> int: ...
