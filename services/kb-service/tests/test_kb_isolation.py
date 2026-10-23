"""The database holds kb's tables to the caller's team (c-507, migration kb_0011), with raw SQL and no WHERE clause as
ops_kb_tenant, by failure mode: a team transaction reading or writing another team's base, source, change or retired
base, and a tenant-wide one reading another tenant's. The tables that need a parent row (links, documents, versions,
chunks, runs) carry the same generated policy, which deploy/database's parity test requires of every marked table."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_kb.store.knowledge import ROLE, kb_bases, kb_changes, kb_retired_bases, kb_sources
from ops_store.conformance import isolation_suite

TABLES = (kb_bases, kb_sources, kb_retired_bases, kb_changes)


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def test_each_table_holds_a_team_to_its_rows(engine: AsyncEngine) -> None:
    assert await isolation_suite(engine, TABLES, role=ROLE) == []
