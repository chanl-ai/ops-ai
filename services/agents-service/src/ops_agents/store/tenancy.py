"""The tenant a statement runs for, and the two ways into the tenant-scoped tables.

The tenant is never a repository argument: `auth.principal` sets it for a request (from the verified token, or
"local" in dev), and the sweeper, timer poller and inbox drain set it inside the task that works one claimed thread,
from that thread's row. Asyncio copies the context into each task it creates, so a run started by a request keeps
the request's tenant, and two threads worked by one sweep never see each other's.

`tenant_tx` is every read and write of graph_threads, graph_runs, thread_events, review_decisions and
review_approvals. It is `ops_store.dialect.tenant_tx`: on PostgreSQL it switches to `ops_runtime_tenant` and sets
`app.tenant_id`, so row-level security (migration 0021) shows and accepts only that tenant's rows whatever the query
says; on SQL Server it sets SESSION_CONTEXT tenant_id for the security policies. The compose superuser bypasses RLS,
which is why the switch is per transaction, as in ops_checkpointer. No tenant set raises, so a code path that forgot
its tenant fails instead of reading another tenant's rows.

`system_tx` is `ops_store.dialect.system_tx` as `ops_runtime_system`: a BYPASSRLS role on PostgreSQL, a user without
a login that only this service may impersonate on SQL Server; on both its grants name what it reads. Only the three
loops use it, and only to find which tenant a claimed thread belongs to; tests/store/test_tenancy.py checks that
nothing else imports it.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import AbstractAsyncContextManager, contextmanager
from contextvars import ContextVar

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_store import dialect

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


def tenant_tx(engine: AsyncEngine) -> AbstractAsyncContextManager[AsyncConnection]:
    return dialect.tenant_tx(engine, current_tenant(), role=TENANT_ROLE)


def system_tx(engine: AsyncEngine) -> AbstractAsyncContextManager[AsyncConnection]:
    return dialect.system_tx(engine, role=SYSTEM_ROLE)
