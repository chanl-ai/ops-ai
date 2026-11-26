# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# asyncpg ships without type information.
"""`make up` migrates the stack's database in place and stops only when a chain is ahead of this checkout
(scripts/schema_sync.py), by failure mode: a service's chain missing from the check, so a database another session
migrated ahead keeps serving code that does not match it; and a chain merely behind the code treated as a reason to
stop or wipe, when migrating forward keeps everyone's data and sessions. Real PostgreSQL and the real chains'
heads; a throwaway database, dropped at the end."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import asyncpg
import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "schema_sync.py"
PORT = os.environ.get("OPS_PG_PORT", "5477")
NAME = f"ops_test_schema_sync_{os.getpid()}"
ADMIN = f"postgresql://ops:ops@localhost:{PORT}/postgres"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("schema_sync", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def build(rows: dict[str, str]) -> None:
    admin = await asyncpg.connect(ADMIN)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{NAME}"')
    finally:
        await admin.close()
    c = await asyncpg.connect(f"postgresql://ops:ops@localhost:{PORT}/{NAME}")
    try:
        for table, version in rows.items():
            await c.execute(f"CREATE TABLE {table} (version_num varchar(32) NOT NULL)")
            await c.execute(f"INSERT INTO {table} VALUES ($1)", version)  # noqa: S608
    finally:
        await c.close()


async def drop() -> None:
    admin = await asyncpg.connect(ADMIN)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)')
    finally:
        await admin.close()


@pytest.fixture
def database() -> Iterator[str]:
    try:
        asyncio.run(drop())
    except OSError:
        pytest.skip(f"PostgreSQL is not on :{PORT}; run make db-up")
    yield f"postgresql+asyncpg://ops:ops@localhost:{PORT}/{NAME}"
    asyncio.run(drop())


def check(url: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), url], capture_output=True, text=True, cwd=ROOT, check=False)


def test_a_kb_chain_ahead_of_the_code_stops_make_up_and_names_the_fix(database: str) -> None:
    sync = load()
    chains: tuple[tuple[str, str, str], ...] = sync.CHAINS
    heads: dict[str, str] = {table: sync.code_head(directory) for _, directory, table in chains}
    asyncio.run(build(heads))
    assert check(database).returncode == 0, "every chain at its head is in sync"
    asyncio.run(build({**heads, "alembic_version_kb": "9999_from_newer_code"}))
    ahead = check(database)
    assert ahead.returncode == 4, ahead.stdout + ahead.stderr
    assert "kb database at 9999_from_newer_code" in ahead.stdout and "make reset-db" in ahead.stdout, ahead.stdout


def test_a_chain_behind_the_code_is_migrated_not_wiped(database: str) -> None:
    sync = load()
    chains: tuple[tuple[str, str, str], ...] = sync.CHAINS
    heads: dict[str, str] = {table: sync.code_head(directory) for _, directory, table in chains}
    # platform's first revision: a database built by older code, which make up migrates forward.
    script = sync.ScriptDirectory.from_config(sync.Config(str(sync.ROOT / "services/platform-service/alembic.ini")))
    first = next(r.revision for r in script.walk_revisions() if r.down_revision is None)
    asyncio.run(build({**heads, "alembic_version_platform": first}))
    behind = check(database)
    assert behind.returncode == 0, behind.stdout + behind.stderr
    assert f"platform database at {first}" in behind.stdout and "migrates it forward" in behind.stdout, behind.stdout


def refused(url: str, *flags: str, **env: str) -> str:
    """The refusal message, or fails: URLs here point at port 1, so a guard that lets a call through cannot reach a
    database, it errors on the connection instead."""
    out = subprocess.run(
        [sys.executable, str(SCRIPT), url, *flags],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, **env},
        check=False,
    )
    assert out.returncode != 0 and "refusing" in out.stdout + out.stderr, (flags, out.stdout, out.stderr[-300:])
    return out.stdout + out.stderr


def test_a_reset_of_a_stack_database_needs_the_flag_only_make_reset_db_passes() -> None:
    url = "postgresql+asyncpg://ops:ops@localhost:1/ops_runtime"
    assert "only make reset-db" in refused(url, "--reset")


def test_a_shared_stack_never_resets_or_creates_a_database_but_its_own() -> None:
    env = {"OPS_INFRA": "shared", "OPS_PORT_OFFSET": "400"}
    for name in ("ops_runtime", "ops_runtime_300"):
        url = f"postgresql+asyncpg://ops:ops@localhost:1/{name}"
        assert "owns only ops_runtime_400" in refused(url, "--reset", "--confirmed-by-reset-db", **env)
        assert "owns only ops_runtime_400" in refused(url, "--create", **env)


def test_create_makes_a_missing_database_once_and_leaves_an_existing_one(database: str) -> None:
    asyncio.run(drop())
    # ops_test_ names are the test runners'; the create path takes any other name.
    scratch = database.rsplit("/", 1)[0] + f"/ops_scratch_{os.getpid()}"

    def create() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), scratch, "--create"], capture_output=True, text=True, cwd=ROOT, check=False
        )

    async def exists(drop_it: bool = False) -> bool:
        admin = await asyncpg.connect(ADMIN)
        try:
            name = f"ops_scratch_{os.getpid()}"
            found = bool(await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name))
            if drop_it:
                await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            return found
        finally:
            await admin.close()

    try:
        first, second = create(), create()
        assert first.returncode == 0 and "created" in first.stdout, first.stdout + first.stderr
        assert second.returncode == 0 and "created" not in second.stdout, second.stdout + second.stderr
        assert asyncio.run(exists())
    finally:
        asyncio.run(exists(drop_it=True))
