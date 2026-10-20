"""An API key's traffic on the Channels list (c-246), on PostgreSQL under the tenant role: a thread a key started is
counted by the `startedBy` its metadata holds, a JSON read that SQLite answers more loosely than PostgreSQL; another
tenant's thread under the same key id counts nothing. Runs on the migrated test database."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.channel_list import ChannelList
from ops_agents.store.graphs import GraphStore
from ops_agents.store.tenancy import tenant_scope


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def test_a_keys_threads_count_in_its_tenant_only(engine: AsyncEngine) -> None:
    kid = f"key_{uuid4().hex[:10]}"
    now = datetime.now(UTC)
    at = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    ours, theirs = f"t-{uuid4().hex[:6]}", f"t-{uuid4().hex[:6]}"
    for tenant in (ours, ours, theirs):
        with tenant_scope(tenant):
            meta = {"ownerEmail": "case-system@northfield.example", "startedBy": f"key:{kid}"}
            await GraphStore(engine).create_thread(f"gth_{uuid4().hex[:10]}", "agent:ag_x", meta, "team_ops", at)
    key = {"id": kid, "name": "CI", "prefix": kid, "teamId": "team_ops", "status": "active", "target": None}
    with tenant_scope(ours):
        [row] = await ChannelList(engine).api_rows([key], now=now)
    assert (row["counts"].traffic24h, row["counts"].activity7d) == (2, 2), row["counts"]
