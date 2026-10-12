"""Alembic environment: the database URL comes from Settings, the one place env is read (spec 17 rule 4)."""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.store import channels as _channels  # noqa: F401 - registers the channel tables
from ops_agents.store import events as _events  # noqa: F401 - registers thread_events
from ops_agents.store import leases as _leases  # noqa: F401 - registers thread_leases on the metadata
from ops_agents.store import model_calls as _model_calls  # noqa: F401 - registers model_call_records
from ops_agents.store import reviews as _reviews  # noqa: F401 - registers review_decisions and review_approvals
from ops_agents.store import usage as _usage  # noqa: F401 - registers thread_budgets
from ops_agents.store.graphs import metadata
from ops_service_kit.settings import Settings

URL = Settings().database_url


def _ours(name: str | None, type_: str, _parent: object) -> bool:
    """Only the Runtime's own tables; LangGraph's checkpointer creates and migrates its tables itself."""
    return type_ != "table" or name in metadata.tables


def run_offline() -> None:
    context.configure(url=URL, target_metadata=metadata, literal_binds=True, include_name=_ours)
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
