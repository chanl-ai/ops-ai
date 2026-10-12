"""Guarantees a repository needs from its database, and the backends that provide them."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar, Protocol, runtime_checkable


class Guarantee(StrEnum):
    # A conditional write that applies only when a value still matches what was read (a generation, a status).
    CAS = "cas"
    # Several writes that all land or none do.
    TRANSACTION = "transaction"
    # A lock that serialises writers on one key across processes (an advisory lock).
    LOCK = "lock"
    # One clock every process agrees on, read from the database rather than the host.
    CLOCK = "clock"
    # Row-level security: the database itself hides rows outside the caller's tenant.
    RLS = "rls"


@runtime_checkable
class Repository(Protocol):
    """A service's door to one part of its database. `requires` names what its correctness depends on, so a
    backend that lacks one is refused before the repository is used on it."""

    requires: ClassVar[frozenset[Guarantee]]


@dataclass(frozen=True)
class Backend:
    """A database a repository can run on, and the guarantees it provides."""

    name: str
    url: str
    provides: frozenset[Guarantee] = field(default_factory=frozenset[Guarantee])


def unmet(repository: type[Repository] | Repository, backend: Backend) -> frozenset[Guarantee]:
    """The guarantees `repository` requires that `backend` does not provide; empty when it may run there."""
    return repository.requires - backend.provides
