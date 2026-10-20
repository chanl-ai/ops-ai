"""A database connection the server closed while the pool held it (idle timeout, failover, restart) is replaced on the
next checkout, so the first request after an idle spell does not fail with "connection is closed" (c-384)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_platform.store.tenancy import TenantDb


async def test_a_pooled_connection_the_server_closed_is_replaced_before_use(
    database_url: str, engine: AsyncEngine
) -> None:
    db = TenantDb.open(database_url)
    try:
        async with db.tenant_tx(None) as c:
            pid = (await c.execute(sa.text("select pg_backend_pid()"))).scalar_one()
        async with engine.connect() as admin:
            await admin.execute(sa.text("select pg_terminate_backend(:pid)"), {"pid": pid})
        async with db.tenant_tx(None) as c:
            assert (await c.execute(sa.text("select pg_backend_pid()"))).scalar_one() != pid
    finally:
        await db.engine.dispose()
