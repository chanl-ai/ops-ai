"""Every checkpoint is in exactly one team: the Runtime's saver writes under the context's team, refuses a write when
the context names none, and a tenant-wide read finds a thread whichever team holds it."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from langgraph.checkpoint.base import empty_checkpoint

from ops_agents.graphs.checkpointer import open_checkpointer
from ops_agents.store.tenancy import tenant_scope
from ops_checkpointer.tables import ops_checkpoints
from ops_store import isolation
from ops_store.database import open_database


def _config(thread_id: str) -> Any:
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}


async def test_a_checkpoint_write_with_no_team_is_refused(database_url: str) -> None:
    tenant, thread_id = f"t-{uuid4().hex}", f"th-{uuid4().hex}"
    async with open_checkpointer(database_url) as saver:
        with tenant_scope(tenant), pytest.raises(RuntimeError, match="team"):
            await saver.aput(_config(thread_id), empty_checkpoint(), {"source": "input", "step": -1}, {})


async def test_a_write_lands_in_the_context_team_and_a_tenant_wide_read_finds_it(database_url: str) -> None:
    tenant, thread_id = f"t-{uuid4().hex}", f"th-{uuid4().hex}"
    async with open_checkpointer(database_url) as saver:
        with isolation.scope(tenant, "team_a"):
            await saver.aput(_config(thread_id), empty_checkpoint(), {"source": "input", "step": -1}, {})
        with isolation.scope(tenant, "team_b"):
            assert await saver.aget_tuple(_config(thread_id)) is None
        with tenant_scope(tenant):
            assert await saver.aget_tuple(_config(thread_id)) is not None
    db = open_database(database_url)
    try:
        async with db.connect() as c:
            teams = (
                (await c.execute(sa.select(ops_checkpoints.c.team_id).where(ops_checkpoints.c.thread_id == thread_id)))
                .scalars()
                .all()
            )
    finally:
        await db.dispose()
    assert teams == ["team_a"]
