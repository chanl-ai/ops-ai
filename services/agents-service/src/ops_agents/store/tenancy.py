"""The tenant a statement runs for, and the two ways into the tenant-scoped tables.

The tenant is never a repository argument: `auth.principal` sets it for a request (from the verified token, or
"local" in dev), and the sweeper, timer poller and inbox drain set it inside the task that works one claimed thread,
from that thread's row. Asyncio copies the context into each task it creates, so a run started by a request keeps
the request's tenant, and two threads worked by one sweep never see each other's.

`tenant_tx` is every read and write of graph_threads, graph_runs, thread_events, review_decisions and
review_approvals. On PostgreSQL it switches to `ops_runtime_tenant` and sets `app.tenant_id`, so row-level security
(migration 0021) shows and accepts only that tenant's rows whatever the query says; the compose superuser bypasses
RLS, which is why the switch is per transaction, as in ops_checkpointer. No tenant set raises, so a code path that
forgot its tenant fails instead of reading another tenant's rows.

`system_tx` switches to `ops_runtime_system`, which bypasses RLS. Only the three loops use it, and only to find which
tenant a claimed thread belongs to; tests/store/test_tenancy.py checks that nothing else imports it.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

LOCAL_TENANT = "local"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"

_tenant: ContextVar[str | None] = ContextVar("ops_tenant", default=None)
# The team a request acts in; unset for the loops, which act for a thread whatever its team.
_team: ContextVar[str | None] = ContextVar("ops_team", default=None)


class NoTenantError(RuntimeError):
    """A tenant-scoped statement ran with no tenant set."""


def current_tenant() -> str:
    tenant = _tenant.get()
    if not tenant:
        raise NoTenantError("no tenant is set for this statement; requests set it in auth.principal")
    return tenant


def set_tenant(tenant_id: str) -> None:
    """For a request: the dependency's context is the endpoint's, so the value lasts the request."""
    _tenant.set(tenant_id)


def set_team(team_id: str | None) -> None:
    _team.set(team_id)


def current_team() -> str | None:
    return _team.get()


@contextmanager
def tenant_scope(tenant_id: str) -> Generator[None]:
    """For a loop's per-thread task, and for tests."""
    token = _tenant.set(tenant_id)
    try:
        yield
    finally:
        _tenant.reset(token)


@asynccontextmanager
async def tenant_tx(engine: AsyncEngine) -> AsyncGenerator[AsyncConnection]:
    tenant = current_tenant()
    async with engine.begin() as c:
        if engine.dialect.name == "postgresql":
            await c.execute(sa.text(f"SET LOCAL ROLE {TENANT_ROLE}"))
            await c.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant})
        yield c


@asynccontextmanager
async def system_tx(engine: AsyncEngine) -> AsyncGenerator[AsyncConnection]:
    async with engine.begin() as c:
        if engine.dialect.name == "postgresql":
            await c.execute(sa.text(f"SET LOCAL ROLE {SYSTEM_ROLE}"))
        yield c
