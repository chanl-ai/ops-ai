"""Alembic environment: the database URL comes from Settings, the one place env is read (spec 17 rule 4)."""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

# Each import registers its module's tables on the metadata.
import ops_agents.store.background  # pyright: ignore[reportUnusedImport]
import ops_agents.store.channels  # pyright: ignore[reportUnusedImport]
import ops_agents.store.events  # pyright: ignore[reportUnusedImport]
import ops_agents.store.graphs  # pyright: ignore[reportUnusedImport]
import ops_agents.store.guardrails  # pyright: ignore[reportUnusedImport]
import ops_agents.store.leases  # pyright: ignore[reportUnusedImport]
import ops_agents.store.reviews  # pyright: ignore[reportUnusedImport]
import ops_agents.store.skills  # noqa: F401  # pyright: ignore[reportUnusedImport]
from ops_agents.store.base import metadata
from ops_service_kit.settings import Settings
from ops_store.schema import offline_dialect_opts

URL = Settings().database_url


def _ours(name: str | None, type_: str, _parent: object) -> bool:
    """Only the Runtime's own tables; LangGraph's checkpointer creates and migrates its tables itself."""
    return type_ != "table" or name in metadata.tables


def run_offline() -> None:
    context.configure(
        url=URL,
        target_metadata=metadata,
        literal_binds=True,
        include_name=_ours,
        dialect_opts=offline_dialect_opts(URL),
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=metadata, include_name=_ours)
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
