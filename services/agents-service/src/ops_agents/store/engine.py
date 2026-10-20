"""The workflow runner's door to this service's tenancy: ops_engine's stores run their statements through these
transactions, so engine rows get the same forced row-level security as the run tables (store/tenancy.py). The
system transaction serves one statement: the worker claiming a work row (ops_engine.store.work)."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_store.database import open_database

from .leases import check_fence
from .tenancy import current_tenant, system_tx, tenant_tx

__all__ = ["AsyncEngine", "DatabaseError", "EngineTransactions", "connect"]

# What a statement on the runner's tables raises on a database not yet migrated to them (or any driver error).
DatabaseError = DBAPIError


def connect(database_url: str) -> AsyncEngine:
    """The worker process's database engine."""
    return open_database(database_url)


class EngineTransactions:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    def tenant(self) -> str:
        return current_tenant()

    def tenant_tx(self) -> AbstractAsyncContextManager[AsyncConnection]:
        return tenant_tx(self.engine)

    async def check_fence(self, conn: AsyncConnection, thread_id: str, generation: int | None) -> None:
        await check_fence(conn, thread_id, generation)

    def system_tx(self, reason: str) -> AbstractAsyncContextManager[AsyncConnection]:
        # The worker's claim of engine_work and the listener's live workflows, before the row's tenant is known; the
        # migrations grant nothing else. The reason is ops_engine's.
        return system_tx(self.engine, reason)
