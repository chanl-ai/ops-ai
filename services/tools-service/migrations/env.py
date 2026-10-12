"""Alembic environment for tools-service: its own chain, recorded in `alembic_version_tools`, on the shared database.

The database URL comes from Settings, the one place env is read (spec 17 rule 4). Autogenerate sees only the tables
in METADATA, so this chain never proposes changes to agents-service's tables, nor theirs to ours.
"""

from __future__ import annotations

import asyncio

import sqlalchemy as sa
from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from ops_service_kit.settings import Settings
from ops_tools.store import metadata as gateway_metadata
from ops_tools.store.modules import metadata as modules_metadata

# One entry per module that owns tables.
METADATA: list[sa.MetaData] = [gateway_metadata, modules_metadata]
VERSION_TABLE = "alembic_version_tools"
URL = Settings().database_url
OURS = {name for m in METADATA for name in m.tables}


def _ours(name: str | None, type_: str, _parent: object) -> bool:
    return type_ != "table" or name in OURS


def _configure(**kwargs: object) -> None:
    context.configure(target_metadata=METADATA, version_table=VERSION_TABLE, include_name=_ours, **kwargs)  # pyright: ignore[reportArgumentType]


def run_offline() -> None:
    _configure(url=URL, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(URL)
    async with engine.connect() as c:
        await c.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
