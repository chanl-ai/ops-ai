# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false
# asyncpg ships without type information.
"""tools-service owns its tables and answers for its registry: the review service asks it over HTTP for a tool's
access class, and its own migration chain creates its tables on a fresh database and adopts them on one the agents
chain already migrated, without touching their rows."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from ops_agents.activities.gateway import GatewayClient
from ops_identity import ServiceClient, dev_service_signer

from .conftest import Gateway

SERVICES = Path(__file__).parents[3]
ADMIN = "postgresql://ops:ops@localhost:5477/postgres"


async def test_tool_access_is_internal_and_comes_from_the_gateway_registry(gateway: Gateway) -> None:
    assert (await gateway.client.get("/v1/tools/place_wire_hold", headers={"Authorization": ""})).status_code == 401
    tools = GatewayClient(
        ServiceClient(gateway.client, dev_service_signer(), "agents", "tools", tenant=lambda: "local")
    )
    assert await tools.tool_access("place_wire_hold") == "write"
    assert await tools.tool_access("send_reply") == "write"
    assert await tools.tool_access("lookup_account") == "read"
    assert await tools.tool_access("drop_tables") == "unknown"


async def _scalar(db: str, sql: str) -> object:
    conn = await asyncpg.connect(ADMIN.replace("/postgres", f"/{db}"))
    try:
        return await conn.fetchval(sql)
    finally:
        await conn.close()


@pytest.fixture
async def fresh_database() -> AsyncGenerator[str]:
    """An empty database for one test, dropped after it. The name carries this process's pid, so
    scripts/scratch_db_sweep.py drops it if the run dies before the drop."""
    db = f"ops_tools_p{os.getpid()}_{uuid4().hex[:8]}"
    conn = await asyncpg.connect(ADMIN)
    await conn.execute(f"CREATE DATABASE {db}")
    await conn.close()
    try:
        yield db
    finally:
        conn = await asyncpg.connect(ADMIN)
        try:
            await conn.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
        finally:
            await conn.close()


def _tools_head() -> str | None:
    return ScriptDirectory.from_config(Config(str(SERVICES / "tools-service" / "alembic.ini"))).get_current_head()


def _upgrade(service: str, db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_DATABASE_URL", f"postgresql+asyncpg://ops:ops@localhost:5477/{db}")
    command.upgrade(Config(str(SERVICES / service / "alembic.ini")), "head")


async def test_tools_chain_creates_its_tables_on_a_fresh_database(
    fresh_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = fresh_database
    await asyncio.to_thread(_upgrade, "tools-service", db, monkeypatch)
    assert await _scalar(db, "SELECT version_num FROM alembic_version_tools") == _tools_head()
    assert await _scalar(db, "SELECT to_regclass('alembic_version')") is None  # the agents chain was not involved


_CALL = (
    "INSERT INTO gateway_calls (id, tool, access, input_hash, idempotency_key, thread_id, step, sub, decision,"
    " reasons, approvers, outcome, effect, effect_scope, tenant_id, created_at) VALUES ('{id}', 'place_wire_hold',"
    " 'write', 'h1', 'k-{id}', 'th_1', 's1', 'u', 'allow', '[]', '[]', 'ok', {effect}, '{scope}', 't1',"
    " '2026-10-17T00:00:00Z')"
)


async def test_a_write_acts_once_per_scope_and_step_by_a_unique_index(
    fresh_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Migration 0017 replaced the partial index ux_gateway_calls_effect with a plain unique index on effect_scope:
    # a second row holding the same write's side effect must be refused, while rows without one never collide.
    db = fresh_database
    await asyncio.to_thread(_upgrade, "tools-service", db, monkeypatch)
    conn = await asyncpg.connect(ADMIN.replace("/postgres", f"/{db}"))
    try:
        await conn.execute(_CALL.format(id="c1", effect="true", scope="thread:th_1"))
        with pytest.raises(asyncpg.UniqueViolationError, match="ux_gateway_calls_effect_scope"):
            await conn.execute(_CALL.format(id="c2", effect="true", scope="thread:th_1"))
        await conn.execute(_CALL.format(id="c3", effect="false", scope="row:c3"))
        await conn.execute(_CALL.format(id="c4", effect="false", scope="row:c4"))
    finally:
        await conn.close()


async def test_tools_chain_adopts_tables_the_agents_chain_created(
    fresh_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = fresh_database
    await asyncio.to_thread(_upgrade, "agents-service", db, monkeypatch)
    await _scalar(db, "INSERT INTO gateway_fences VALUES ('gth_keep', 7) RETURNING 1")
    await asyncio.to_thread(_upgrade, "tools-service", db, monkeypatch)
    assert await _scalar(db, "SELECT version_num FROM alembic_version_tools") == _tools_head()
    assert await _scalar(db, "SELECT generation FROM gateway_fences WHERE thread_id = 'gth_keep'") == 7
