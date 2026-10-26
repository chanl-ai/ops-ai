"""platform-service's binding of `ops_store.isolation` (c-411): its database role and the reasons a lookup runs before
the tenant is known.

`tenant_tx(tenant_id)` is how every tenant read and write runs: `isolation.isolated_tx` as `ops_platform_tenant`, so
row-level security (migration 0001) on PostgreSQL and the security policies on SQL Server show and accept only that
tenant's rows, whatever the query says. The tenant is the verified session's, key's or invite's, or the one a pre-tenant
lookup returned; platform-service issues tokens and resolves its own sessions, so it names the tenant per transaction
instead of entering a request context. Its governance tables are workspace-level (TENANT_SCOPED, no team). No tenant
raises `NoTenantError`.

`system_tx(reason)` runs as the same role with no tenant set, so it reads no table rows at all. It exists for the
lookups that come before the tenant is known (sign-in by email, a session by id, a key by prefix, an invite by token
hash), which call the SECURITY DEFINER functions of migration 0004 and get back only the columns those need; each names
a reason below, listed in `packages/ops_store/tests/test_isolation_sites.py`.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_store import isolation
from ops_store.database import open_database

ROLE = "ops_platform_tenant"

# Why a lookup runs before its tenant is known.
SIGNIN_LOOKUP = "signin_lookup"  # people by email, a sign-in domain, an SSO flow by its state or handoff
SESSION_LOOKUP = "session_lookup"  # a session by id
KEY_LOOKUP = "key_lookup"  # an API key by its id
INVITE_LOOKUP = "invite_lookup"  # an invitation by its token hash
SIGNIN_LOCKOUT = "signin_lockout"  # failed sign-ins counted by email hash (signin_email_failures holds no tenant)
RESET_LOOKUP = "reset_lookup"  # a password reset by its token hash
PURGE_LOOKUP = "purge_lookup"  # workspaces closed longer than the restore window, for the purge loop (c-529)


class TenantDb:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    @classmethod
    def open(cls, url: str) -> TenantDb:
        return cls(open_database(url))

    @asynccontextmanager
    async def tenant_tx(self, tenant_id: str | None) -> AsyncGenerator[AsyncConnection]:
        """One transaction as `tenant_id`, workspace-level (no team); None raises `NoTenantError`."""
        with isolation.scope(tenant_id or "", None):
            async with isolation.isolated_tx(self.engine, role=ROLE) as c:
                yield c

    def system_tx(self, reason: str) -> AbstractAsyncContextManager[AsyncConnection]:
        """One transaction with no tenant, for the lookup functions that find one."""
        return isolation.system_tx(self.engine, reason, role=ROLE)
