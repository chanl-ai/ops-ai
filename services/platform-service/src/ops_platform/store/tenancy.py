"""The two ways into platform-service's database.

`tenant_tx(tenant_id)` is how every tenant read and write runs: inside one transaction it switches to the
`ops_platform_tenant` role and sets `app.tenant_id`, so row-level security (migration 0001) shows and accepts only that
tenant's rows, whatever the query says. The deployment connects as a role that owns no tables; the compose superuser
bypasses RLS, which is why the switch is per transaction, as in ops_checkpointer.

`system_tx()` runs as the same role with no tenant set, so it reads no table rows at all. It exists for the lookups
that come before the tenant is known (sign-in by email, a session by id, a key by prefix, an invite by token hash),
which call the SECURITY DEFINER functions of migration 0004 and get back only the columns those need.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_store.database import open_database

ROLE = "ops_platform_tenant"


class TenantDb:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    @classmethod
    def open(cls, url: str) -> TenantDb:
        return cls(open_database(url))

    @asynccontextmanager
    async def tenant_tx(self, tenant_id: str | None) -> AsyncGenerator[AsyncConnection]:
        """One transaction as `tenant_id`; None sees and writes nothing."""
        async with self.engine.begin() as c:
            await c.execute(sa.text(f"SET LOCAL ROLE {ROLE}"))
            await c.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id or ""})
            yield c

    @asynccontextmanager
    async def system_tx(self) -> AsyncGenerator[AsyncConnection]:
        """One transaction with no tenant, for the lookup functions that find one."""
        async with self.engine.begin() as c:
            await c.execute(sa.text(f"SET LOCAL ROLE {ROLE}"))
            yield c
