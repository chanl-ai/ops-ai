"""agents-service's binding of `ops_store.isolation`: its database roles and the reasons its paths act wider
than one team.

The context is never a repository argument and never set here: `ops_identity` enters it for each request from the
verified caller, and a loop enters it inside the task that works one claimed item, through `isolation.tenant_wide`
with one of the reasons below. Asyncio copies the context into each task it creates, so a run started by a request
keeps the request's tenant, and two threads worked by one sweep never see each other's.

Every store class extends `RuntimeStore`, which is `ops_store.Store` with this service's two roles. Its `tx()` is every
read and write of a tenant-scoped table: `isolation.isolated_tx` as `ops_runtime_tenant`, so row-level security
(migration 0021) or the SQL Server security policies show and accept only the context's rows whatever the query says.
The compose superuser bypasses RLS, which is why the role switch is per transaction, as in ops_checkpointer. No context
raises `NoTenantError`, so a path that forgot its caller fails instead of reading.

`tenant_tx(engine)` is an alias of `RuntimeStore(engine).tx()`, for code that holds an engine and no store; the context
names the tenant, so nothing is passed per call (platform-service names it per transaction, this service does not).

`system_tx` is the base's `system_tx(reason)`, `isolation.system_tx` as `ops_runtime_system`: a BYPASSRLS role on
PostgreSQL, a user without a login that only this service may impersonate on SQL Server; on both its grants name what it
reads. It takes a reason; `packages/ops_store/tests/test_isolation_sites.py` lists each call site by reason.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import AbstractAsyncContextManager, contextmanager

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_store import isolation
from ops_store.isolation import NoTenantError
from ops_store.store import Store

LOCAL_TENANT = "local"
TENANT_ROLE = "ops_runtime_tenant"
SYSTEM_ROLE = "ops_runtime_system"

# Why a path acts for every team of one tenant (`isolation.tenant_wide`). Each loop is to narrow to the claimed
# row's team (the sweeper and the timer poller already act as the thread's team); until then each acts for the
# tenant under its own name.
SEED = "seed"  # the dev seed writes records of every team into the local tenant
ENGINE_PASS = "engine_pass"  # the workflow worker runs one claimed run's pass
MEMORY_RETENTION = "memory_retention"  # the retention sweep expires one tenant's memories
MAIL_LISTENER = "mail_listener"  # the mailbox listener polls one tenant's bound mailboxes
RUN_RECONCILER = "run_reconciler"  # the run reconciler gives one tenant's run with nothing behind it its state
TESTS = "tests"  # `tenant_scope`, which tests use to act for a tenant
ASSISTANT_CATCH_UP = "assistant_catch_up"  # start-up: one tenant's Ops Assistants brought to the declared version
OWNER = "owner_team"  # a registry record's owning team, read across teams only to decide a refusal (`owner_teams`)

# Why a path reads past the tenant (`isolation.system_tx`): only to find the tenant of what it claimed.
CLAIM_THREAD = "claim_thread"  # GraphStore.owner_of, for the sweeper and the timer poller
RETENTION_TENANTS = "retention_tenants"  # Memories.tenants, for the retention sweep
ASSISTANT_TEAMS = "assistant_teams"  # TeamDefaults.on_agents, for the start-up Ops Assistant catch-up

# Why a path reaches the install's own tables with no tenant (`Store.install_tx`): both are marked `system(...)`.
THREAD_LEASES = "thread_leases"  # a thread's lease, taken, renewed, swept and fenced by thread id before its tenant
TIMERS = "timers"  # a thread's timers, armed, claimed and closed by the poller across every tenant

current_tenant = isolation.tenant
current_team = isolation.team

__all__ = [
    "ASSISTANT_CATCH_UP",
    "ASSISTANT_TEAMS",
    "CLAIM_THREAD",
    "ENGINE_PASS",
    "LOCAL_TENANT",
    "MAIL_LISTENER",
    "MEMORY_RETENTION",
    "OWNER",
    "RETENTION_TENANTS",
    "RUN_RECONCILER",
    "SEED",
    "SYSTEM_ROLE",
    "TENANT_ROLE",
    "TESTS",
    "THREAD_LEASES",
    "TIMERS",
    "NoTenantError",
    "RuntimeStore",
    "current_team",
    "current_tenant",
    "system_tx",
    "tenant_scope",
    "tenant_tx",
]


class RuntimeStore(Store):
    role = TENANT_ROLE
    system_role = SYSTEM_ROLE


def tenant_tx(engine: AsyncEngine) -> AbstractAsyncContextManager[AsyncConnection]:
    return RuntimeStore(engine).tx()


def system_tx(engine: AsyncEngine, reason: str) -> AbstractAsyncContextManager[AsyncConnection]:
    return RuntimeStore(engine).system_tx(reason)


@contextmanager
def tenant_scope(tenant_id: str) -> Generator[None]:
    """For tests: every team of `tenant_id`. Source code names its own reason; the site guard refuses this there."""
    with isolation.tenant_wide(TESTS, tenant_id=tenant_id):
        yield
