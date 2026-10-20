"""The one MetaData every agents-service table registers on; Alembic's env and the SQLite test schema read it."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

metadata = sa.MetaData()


async def ping(engine: AsyncEngine) -> None:
    """Raises when the database does not answer."""
    async with engine.connect() as c:
        await c.execute(sa.text("select 1"))
