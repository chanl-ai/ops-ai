"""Row-level security on the checkpoint tables: one database, two tenants, and neither reads the other's rows."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from langgraph.checkpoint.base import empty_checkpoint
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_checkpointer import RLS_ROLE, CheckpointSaver


def _config(thread_id: str) -> Any:
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}


async def _as(conn: AsyncConnection, role: str | None, tenant: str | None, team: str = "team") -> None:
    if role:
        await conn.execute(sa.text(f"SET LOCAL ROLE {role}"))
    if tenant:
        await conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant})
        await conn.execute(sa.text("SELECT set_config('app.team_id', :t, true)"), {"t": team})


async def _count(db: AsyncEngine, thread_id: str, tenant: str | None, role: str | None, team: str = "team") -> int:
    """Counts the thread's rows with no tenant or team in the WHERE clause, so only the policy can filter them."""
    async with db.begin() as conn:
        await _as(conn, role, tenant, team)
        query = sa.text("SELECT count(*) FROM ops_checkpoints WHERE thread_id = :t")
        return int((await conn.execute(query, {"t": thread_id})).scalar_one())


async def test_cross_tenant_get_returns_nothing(db: AsyncEngine) -> None:
    a = CheckpointSaver(db, tenant_id=f"a-{uuid4().hex}", team_id="team", role=RLS_ROLE)
    b = a.for_scope(f"b-{uuid4().hex}", "team")
    thread_id = f"t-{uuid4().hex}"
    await a.aput(_config(thread_id), empty_checkpoint(), {"source": "input", "step": -1}, {})

    assert await a.aget_tuple(_config(thread_id)) is not None
    assert await b.aget_tuple(_config(thread_id)) is None
    assert [t async for t in b.alist(_config(thread_id))] == []
    assert [t async for t in b.alist(None)] == []

    # The policy, not the saver's WHERE clause, is what hides the row.
    assert await _count(db, thread_id, a.tenant_id, RLS_ROLE) == 1
    assert await _count(db, thread_id, b.tenant_id, RLS_ROLE) == 0
    assert await _count(db, thread_id, None, RLS_ROLE) == 0
    # The compose user is a superuser and bypasses the policy, which is why the saver switches role.
    assert await _count(db, thread_id, None, None) == 1


async def test_cross_tenant_write_is_refused(db: AsyncEngine) -> None:
    tenant_a, tenant_b = f"a-{uuid4().hex}", f"b-{uuid4().hex}"
    async with db.connect() as conn:
        await conn.begin()
        await _as(conn, RLS_ROLE, tenant_a)
        with pytest.raises(DBAPIError, match="row-level security"):
            await conn.execute(
                sa.text(
                    "INSERT INTO ops_checkpoints (tenant_id, team_id, thread_id, checkpoint_id, type, checkpoint,"
                    " metadata_type, metadata_blob) VALUES (:t, 'team', 't', 'c', 'null', ''::bytea, 'null', ''::bytea)"
                ),
                {"t": tenant_b},
            )


async def test_another_team_of_the_tenant_reads_no_checkpoint(db: AsyncEngine) -> None:
    a = CheckpointSaver(db, tenant_id=f"a-{uuid4().hex}", team_id="team", role=RLS_ROLE)
    thread_id = f"t-{uuid4().hex}"
    await a.aput(_config(thread_id), empty_checkpoint(), {"source": "input", "step": -1}, {})

    assert await a.for_scope(a.tenant_id, "other").aget_tuple(_config(thread_id)) is None
    # The team policy, not the saver's WHERE clause, is what hides the row.
    assert await _count(db, thread_id, a.tenant_id, RLS_ROLE, team="team") == 1
    assert await _count(db, thread_id, a.tenant_id, RLS_ROLE, team="other") == 0
