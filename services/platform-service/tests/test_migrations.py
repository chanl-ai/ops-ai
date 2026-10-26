"""The platform chain migrates up from nothing and back down, in its own version table, beside the other services'.
Synchronous: Alembic's environment runs its own event loop."""

from __future__ import annotations

import asyncio

import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from ops_platform.store.tables import metadata

from .conftest import alembic_config


async def tables_and_version(url: str) -> tuple[set[str], str | None]:
    engine = create_async_engine(url)
    async with engine.connect() as c:
        names = set(await c.run_sync(lambda s: sa.inspect(s).get_table_names()))
        version = None
        if "alembic_version_platform" in names:
            version = (await c.execute(sa.text("select version_num from alembic_version_platform"))).scalar()
    await engine.dispose()
    return names, version


def test_down_to_base_and_up_to_head(database_url: str) -> None:
    ours = set(metadata.tables)
    command.downgrade(alembic_config(), "base")
    names, version = asyncio.run(tables_and_version(database_url))
    assert not ours & names and version is None
    command.upgrade(alembic_config(), "head")
    names, version = asyncio.run(tables_and_version(database_url))
    assert ours <= names and version == "0026_workspace_owner"
