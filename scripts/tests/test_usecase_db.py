# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# asyncpg ships without type information.
"""A use-case database the caller named is rebuilt when a chain is behind (docs/usecases/lib/usecase_db.py), by failure
mode: a database left one migration behind with a row the next migration refuses stops every script at start when it
is migrated in place; one at the head loses its rows to a needless rebuild; and the stack's own database is wiped by a
tool meant only for scratch. Real PostgreSQL and the real tools chain; a throwaway database, dropped at the end."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import asyncpg
import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "services" / "tools-service"
PORT = os.environ.get("OPS_PG_PORT", "5477")
NAME = f"ops_usecase_t{os.getpid()}"
PLAIN = f"postgresql://ops:ops@localhost:{PORT}/{NAME}"
URL = f"postgresql+asyncpg://ops:ops@localhost:{PORT}/{NAME}"
ADMIN = f"postgresql://ops:ops@localhost:{PORT}/postgres"
# The revision before tools_0012_access_rw, which adds CHECK (access IN ('read', 'write')) and rewrites no row.
BEFORE_ACCESS_CHECK = "tools_0011_approval_policy"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("usecase_db", ROOT / "docs" / "usecases" / "lib" / "usecase_db.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _admin(sql: str) -> None:
    c = await asyncpg.connect(ADMIN)
    try:
        await c.execute(sql)
    finally:
        await c.close()


def migrate(revision: str) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"OPS_DATABASE_URL": URL}
    argv = ["uv", "run", "--quiet", "alembic", "upgrade", revision]
    return subprocess.run(argv, cwd=TOOLS, env=env, capture_output=True, text=True, check=False)


async def _retired_row() -> None:
    """A module with one money_movement operation, as the chain allowed before Read and Write only."""
    c = await asyncpg.connect(PLAIN)
    try:
        await c.execute(
            "INSERT INTO tool_modules (tenant_id, id, team_id, name, display_name, system, description, type, status,"
            " owner_team, owner_contacts, endpoint, auth, timeout_ms, data_classification, reachable, drift, version,"
            " pending, revision, created_at, updated_at) VALUES ('ten_dev', 'mod_old', 'team_ops', 'old-bank',"
            " 'Old bank', 'Core banking', '', 'http', 'published', 'Payments', '[]', 'https://api.bank.test', '{}',"
            " 5000, 'internal', true, false, '1.0', '{}', 1, now(), now())"
        )
        await c.execute(
            "INSERT INTO module_operations (tenant_id, id, module_id, position, name, tool_id, description, access,"
            " enabled, input, masked_output, rate_limit_per_min, requires_approval, stub) VALUES ('ten_dev', 'op_old',"
            " 'mod_old', 0, 'move_money', 'move_money', 'Moves money.', 'money_movement', true, '[]', '[]', 60, true,"
            " 'null')"
        )
    finally:
        await c.close()


async def _version() -> str | None:
    c = await asyncpg.connect(PLAIN)
    try:
        if not await c.fetchval("SELECT to_regclass('public.alembic_version_tools') IS NOT NULL"):
            return None
        return str(await c.fetchval("SELECT version_num FROM alembic_version_tools"))
    finally:
        await c.close()


@pytest.fixture
def behind() -> Iterator[None]:
    """The use-case database one migration behind the access check, holding a money_movement operation."""
    try:
        asyncio.run(_admin(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)'))
    except OSError:
        pytest.skip(f"PostgreSQL is not on :{PORT}; run make db-up")
    asyncio.run(_admin(f'CREATE DATABASE "{NAME}"'))
    built = migrate(BEFORE_ACCESS_CHECK)
    assert built.returncode == 0, built.stderr[-2000:]
    asyncio.run(_retired_row())
    yield
    asyncio.run(_admin(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)'))


def test_migrating_it_in_place_stops_on_the_retired_row(behind: None) -> None:
    # What every ui script hit at start before the rebuild: the in-place upgrade refuses the old row.
    moved = migrate("heads")
    assert moved.returncode != 0
    assert "ck_module_operations_access" in moved.stderr


def test_a_chain_behind_is_rebuilt_empty_and_then_migrates_to_the_head(behind: None) -> None:
    found = load().rebuild_if_stale(URL)
    assert found and found[0].startswith(f"tools at {BEFORE_ACCESS_CHECK}, code at ")
    assert asyncio.run(_version()) is None
    moved = migrate("heads")
    assert moved.returncode == 0, moved.stderr[-2000:]


def test_a_database_at_the_head_keeps_its_rows(behind: None) -> None:
    db = load()
    asyncio.run(_admin(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)'))
    asyncio.run(_admin(f'CREATE DATABASE "{NAME}"'))
    assert migrate("heads").returncode == 0
    at_head = asyncio.run(_version())
    assert db.rebuild_if_stale(URL) == []
    assert asyncio.run(_version()) == at_head


def test_only_a_use_case_database_is_rebuilt() -> None:
    with pytest.raises(SystemExit, match="only use-case databases"):
        load().rebuild_if_stale(f"postgresql+asyncpg://ops:ops@localhost:{PORT}/ops")
