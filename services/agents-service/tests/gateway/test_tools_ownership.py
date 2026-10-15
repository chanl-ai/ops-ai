# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false
# asyncpg ships without type information.
"""tools-service owns its tables and answers for its registry: the review service asks it over HTTP for a tool's
access class, and its own migration chain creates its tables on a fresh database and adopts them on one the agents
chain already migrated, without touching their rows."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from ops_agents.activities.gateway import GatewayClient

from .conftest import Gateway, service_token

SERVICES = Path(__file__).parents[3]
ADMIN = "postgresql://ops:ops@localhost:5477/postgres"


async def test_tool_access_is_internal_and_comes_from_the_gateway_registry(gateway: Gateway) -> None:
    assert (await gateway.client.get("/v1/tools/place_wire_hold", headers={"Authorization": ""})).status_code == 401
    tools = GatewayClient(gateway.client, token=service_token)
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


async def _fresh_database() -> str:
    db = f"ops_tools_{uuid4().hex[:8]}"
    conn = await asyncpg.connect(ADMIN)
    await conn.execute(f"CREATE DATABASE {db}")
    await conn.close()
    return db


def _tools_head() -> str | None:
    return ScriptDirectory.from_config(Config(str(SERVICES / "tools-service" / "alembic.ini"))).get_current_head()


def _upgrade(service: str, db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_DATABASE_URL", f"postgresql+asyncpg://ops:ops@localhost:5477/{db}")
    command.upgrade(Config(str(SERVICES / service / "alembic.ini")), "head")


async def test_tools_chain_creates_its_tables_on_a_fresh_database(monkeypatch: pytest.MonkeyPatch) -> None:
    db = await _fresh_database()
    await asyncio.to_thread(_upgrade, "tools-service", db, monkeypatch)
    assert await _scalar(db, "SELECT version_num FROM alembic_version_tools") == _tools_head()
    assert await _scalar(db, "SELECT count(*) FROM pg_indexes WHERE indexname = 'ux_gateway_calls_effect'") == 1
    assert await _scalar(db, "SELECT to_regclass('alembic_version')") is None  # the agents chain was not involved


async def test_tools_chain_adopts_tables_the_agents_chain_created(monkeypatch: pytest.MonkeyPatch) -> None:
    db = await _fresh_database()
    await asyncio.to_thread(_upgrade, "agents-service", db, monkeypatch)
    await _scalar(db, "INSERT INTO gateway_fences VALUES ('gth_keep', 7) RETURNING 1")
    await asyncio.to_thread(_upgrade, "tools-service", db, monkeypatch)
    assert await _scalar(db, "SELECT version_num FROM alembic_version_tools") == _tools_head()
    assert await _scalar(db, "SELECT generation FROM gateway_fences WHERE thread_id = 'gth_keep'") == 7
