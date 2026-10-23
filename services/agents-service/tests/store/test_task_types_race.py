"""Task type saves at once (tick 30, c-288), on PostgreSQL: two saves after a publish both read the published version
as the newest, both open the next one, and the second fails on the version key."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents import task_types as tt
from ops_agents.store.task_types import TaskTypeStore
from ops_agents.store.tenancy import tenant_scope


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def test_saves_at_once_after_a_publish_leave_one_draft(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = TaskTypeStore(engine, "team_ops")
    read = TaskTypeStore._row  # pyright: ignore[reportPrivateUsage]

    async def slow_read(self: TaskTypeStore, c: Any, type_id: str, **kw: Any) -> dict[str, Any]:
        # Holds each save between its read and its write, so saves that do not take turns all read the same version.
        row = await read(self, c, type_id, **kw)
        await asyncio.sleep(0.05)
        return row

    content = next(t for t in json.loads(tt.SEED_FILE.read_text()) if t["id"] == "write_approval")
    with tenant_scope(f"t-{uuid4().hex[:8]}"):
        await store.create("raced", content, team_id="team_ops", by="p@x", copied_from=None)
        await store.publish("raced", 1, by="p@x")
        monkeypatch.setattr(TaskTypeStore, "_row", slow_read)
        saved = await asyncio.gather(*(store.save_draft("raced", content, by="p@x") for _ in range(4)))
        assert saved == [2, 2, 2, 2], saved
        assert [v["version"] for v in (await store.get("raced"))["versions"]] == [2, 1]
