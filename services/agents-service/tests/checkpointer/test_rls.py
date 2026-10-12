"""Row-level security on the checkpoint tables: one database, two tenants, and neither reads the other's rows."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from asyncpg import InsufficientPrivilegeError  # pyright: ignore[reportMissingTypeStubs]
from langgraph.checkpoint.base import empty_checkpoint

from ops_checkpointer import RLS_ROLE, AsyncpgSaver, Pool


def _config(thread_id: str) -> Any:
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}


async def _count(pool: Pool, thread_id: str, tenant: str | None, role: str | None) -> int:
    """Counts the thread's rows with no tenant in the WHERE clause, so only the policy can filter them."""
    async with pool.acquire() as conn, conn.transaction():
        if role:
            await conn.execute(f"SET LOCAL ROLE {role}")
        if tenant:
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant)
        return int(await conn.fetchval("SELECT count(*) FROM ops_checkpoints WHERE thread_id = $1", thread_id))


async def test_cross_tenant_get_returns_nothing(pool: Pool) -> None:
    a = AsyncpgSaver(pool, tenant_id=f"a-{uuid4().hex}", team_id="team", role=RLS_ROLE)
    b = a.for_scope(f"b-{uuid4().hex}", "team")
    thread_id = f"t-{uuid4().hex}"
    await a.aput(_config(thread_id), empty_checkpoint(), {"source": "input", "step": -1}, {})

    assert await a.aget_tuple(_config(thread_id)) is not None
    assert await b.aget_tuple(_config(thread_id)) is None
    assert [t async for t in b.alist(_config(thread_id))] == []
    assert [t async for t in b.alist(None)] == []

    # The policy, not the saver's WHERE clause, is what hides the row.
    assert await _count(pool, thread_id, a.tenant_id, RLS_ROLE) == 1
    assert await _count(pool, thread_id, b.tenant_id, RLS_ROLE) == 0
    assert await _count(pool, thread_id, None, RLS_ROLE) == 0
    # The compose user is a superuser and bypasses the policy, which is why the saver switches role.
    assert await _count(pool, thread_id, None, None) == 1


async def test_cross_tenant_write_is_refused(pool: Pool) -> None:
    tenant_a, tenant_b = f"a-{uuid4().hex}", f"b-{uuid4().hex}"
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(f"SET LOCAL ROLE {RLS_ROLE}")
        await conn.execute("SELECT set_config('app.tenant_id', $1, true)", tenant_a)
        with pytest.raises(InsufficientPrivilegeError):
            await conn.execute(
                "INSERT INTO ops_checkpoints (tenant_id, team_id, thread_id, checkpoint_id, type, checkpoint,"
                " metadata_type, metadata_blob) VALUES ($1, 'team', 't', 'c', 'null', ''::bytea, 'null', ''::bytea)",
                tenant_b,
            )
