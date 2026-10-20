"""documents-service's tables, under their own migration chain (alembic_version_documents)."""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store.database import open_database

metadata = sa.MetaData()


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
