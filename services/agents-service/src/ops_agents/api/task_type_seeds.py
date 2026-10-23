"""The task type store with the acting team's seeded general types in place (c-288; per team, c-507): seeded on the
team's first read in this process, so a team made after the migration has them before any workflow uses one. Both
the API and the worker read types through it, so a worker that never served a request still finds the seeds."""

from __future__ import annotations

from ops_store.team_scope import acting_team

from .. import task_types as tt
from ..store.engine import AsyncEngine
from ..store.task_types import TaskTypeStore
from ..store.tenancy import current_tenant
from .deps import Runtime

# Teams whose seeds this process has checked, per database and tenant; a restart checks again, which inserts nothing
# new.
_seeded: set[tuple[int, str, str | None]] = set()


async def seeded_store(db: AsyncEngine, team: str | None = None) -> TaskTypeStore:
    """`team`: the team of the record being served (a run's task), when it is not the acting team."""
    store = TaskTypeStore(db, team)
    key = (id(db), current_tenant(), team or acting_team())
    if key not in _seeded:
        await store.ensure_seeds(tt.seeds())
        _seeded.add(key)
    return store


async def task_type_store(rt: Runtime, team: str | None = None) -> TaskTypeStore:
    return await seeded_store(rt.db, team)


class StoredTaskTypes:
    """The engine's TaskTypePort: a review step's task type pinned from this tenant's published versions."""

    def __init__(self, db: AsyncEngine) -> None:
        self.db = db

    async def pin(self, type_id: str, version: int | None) -> int:
        n, _ = await (await seeded_store(self.db)).published(type_id, version)
        return n
