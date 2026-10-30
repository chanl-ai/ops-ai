"""The database holds memories, their audit and the memories an answer used (c-557), mailboxes, embeds, trigger mail,
chat search, chat attachments and team defaults to the caller's team (c-507, migration 0077), with raw SQL and no WHERE
clause as ops_runtime_tenant, by failure mode: a team transaction reading or writing another team's row, and a
tenant-wide one reading another tenant's. On the PostgreSQL test database migrated to head."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.chat_attachments import chat_attachments
from ops_agents.store.chat_search import chat_search
from ops_agents.store.mailboxes import mailboxes
from ops_agents.store.memories import agent_memories, memory_audit, message_memory_use
from ops_agents.store.team_defaults import team_default_agents
from ops_agents.store.tenancy import TENANT_ROLE
from ops_agents.store.trigger_events import trigger_events
from ops_agents.store.widget_deployments import widget_deployments
from ops_store.conformance import isolation_suite

TABLES = (
    agent_memories,
    chat_attachments,
    chat_search,
    mailboxes,
    memory_audit,
    message_memory_use,
    team_default_agents,
    trigger_events,
    widget_deployments,
)


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def test_each_table_holds_a_team_to_its_rows(engine: AsyncEngine) -> None:
    assert await isolation_suite(engine, TABLES, role=TENANT_ROLE) == []
