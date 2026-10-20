"""The task type store with the tenant's seeded general types in place (c-288): seeded on the tenant's first read in
this process, as service_events seeds the event workflows on a tenant's first event. Both the API and the worker read
types through it, so a worker that never served a request still finds the seeds."""

from __future__ import annotations

from .. import task_types as tt
from ..store.engine import AsyncEngine
from ..store.task_types import TaskTypeStore
from ..store.tenancy import current_tenant
from .deps import Runtime

# Tenants whose seeds this process has checked, per database; a restart checks again, which inserts nothing new.
_seeded: set[tuple[int, str]] = set()


async def seeded_store(db: AsyncEngine) -> TaskTypeStore:
    store = TaskTypeStore(db)
    key = (id(db), current_tenant())
    if key not in _seeded:
        await store.ensure_seeds(tt.seeds())
        _seeded.add(key)
    return store


async def task_type_store(rt: Runtime) -> TaskTypeStore:
    return await seeded_store(rt.db)


class StoredTaskTypes:
    """The engine's TaskTypePort: a review step's task type pinned from this tenant's published versions."""

    def __init__(self, db: AsyncEngine) -> None:
        self.db = db

    async def pin(self, type_id: str, version: int | None) -> int:
        n, _ = await (await seeded_store(self.db)).published(type_id, version)
        return n
