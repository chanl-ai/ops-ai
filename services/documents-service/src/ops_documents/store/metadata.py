"""documents-service's tables, under their own migration chain (alembic_version_documents)."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store.database import open_database

metadata = sa.MetaData()
# The role every transaction runs as; row-level security applies to it (migration documents_0011, c-415).
ROLE = "ops_documents_tenant"
# The role a restart reads every tenant's queued work as, past row-level security; its grants name what it reads.
SYSTEM_ROLE = "ops_documents_system"
# Why the restart reads past the tenant: to pick up every tenant's queued reads and tests again.
RECOVER_PENDING = "recover_pending"


def engine_for(url: str) -> AsyncEngine:
    return open_database(url)


async def reachable(engine: object) -> bool:
    """Whether the database answers; health says degraded when it does not."""
    assert isinstance(engine, AsyncEngine)
    try:
        async with engine.connect() as c:
            await c.execute(sa.text("SELECT 1"))
    except Exception:
        return False
    return True
