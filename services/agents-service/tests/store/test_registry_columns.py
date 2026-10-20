"""The registry tables the migrations build are the ones the code writes: a column the model dropped but a migration
left (registry `owner` after c-171) is NOT NULL with nothing writing it, so every create fails on PostgreSQL."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.store.agent_registry import registry_agents
from ops_agents.store.workflow_registry import registry_workflows


async def test_migrated_registry_tables_have_the_models_columns(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as c:
            for table in (registry_agents, registry_workflows):

                def columns(sync: sa.Connection, name: str = table.name) -> set[str]:
                    return {col["name"] for col in sa.inspect(sync).get_columns(name)}

                found = await c.run_sync(columns)
                assert found == set(table.columns.keys()), table.name
    finally:
        await engine.dispose()
