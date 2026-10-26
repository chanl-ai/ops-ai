# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# asyncpg ships without type information.
"""The scratch database sweep (scripts/scratch_db_sweep.py), by failure mode: a run still writing to its database is
dropped between two tests because the pid in the database's name has exited (a run started under a parent that
returned, or a name made by a process that is gone); a session that connects between the sweep's look and its drop is
killed; the QA runner's database is touched; and a finished run's database is never cleaned up. Real PostgreSQL;
every database here is made and dropped by the test."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import time
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import asyncpg
import pytest

ROOT = Path(__file__).resolve().parents[2]
PORT = os.environ.get("OPS_PG_PORT", "5477")
ADMIN = f"postgresql://ops:ops@localhost:{PORT}/postgres"
# A pid no process holds: pids on macOS and Linux stay below this.
DEAD = 4_000_000


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("scratch_db_sweep", ROOT / "scripts" / "scratch_db_sweep.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sweep = load()


async def exists(name: str) -> bool:
    c = await asyncpg.connect(ADMIN)
    try:
        return bool(await c.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name))
    finally:
        await c.close()


async def admin(sql: str) -> None:
    c = await asyncpg.connect(ADMIN)
    try:
        await c.execute(sql)
    finally:
        await c.close()


@pytest.fixture
def made() -> Iterator[list[str]]:
    names: list[str] = []
    yield names
    for name in names:
        asyncio.run(admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


def make(made: list[str], name: str) -> str:
    asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    made.append(name)
    return name


def test_a_run_still_writing_keeps_its_database_when_the_pid_in_its_name_is_gone(made: list[str]) -> None:
    name = make(made, f"ops_test_r{DEAD}_{os.getpid():x}a")
    asyncio.run(sweep.sweep(ADMIN, dry_run=False))
    assert asyncio.run(exists(name)), "a database written in the last hour was dropped"


def test_a_finished_runs_database_is_dropped_once_it_has_been_quiet(made: list[str]) -> None:
    name = make(made, f"ops_test_r{DEAD}_{os.getpid():x}b")
    asyncio.run(sweep.sweep(ADMIN, dry_run=False, now=time.time() + 2 * sweep.QUIET_S))
    assert not asyncio.run(exists(name))


def test_the_qa_runners_database_is_never_touched(made: list[str]) -> None:
    name = make(made, f"ops_test_head_{DEAD}")
    sibling = make(made, f"ops_test_head_{DEAD}_conformance")
    asyncio.run(sweep.sweep(ADMIN, dry_run=False, now=time.time() + 2 * sweep.QUIET_S))
    assert asyncio.run(exists(name)) and asyncio.run(exists(sibling))


def test_a_session_that_connects_after_the_look_is_not_killed(made: list[str]) -> None:
    name = make(made, f"ops_test_r{DEAD}_{os.getpid():x}c")

    async def run() -> tuple[bool, int]:
        held = await asyncpg.connect(ADMIN.replace("/postgres", f"/{name}"))
        try:
            c = await asyncpg.connect(ADMIN)
            try:
                dropped = await sweep.drop(c, name)  # the sweep saw no session; this one arrived since
            finally:
                await c.close()
            return dropped, await held.fetchval("SELECT 1")
        finally:
            await held.close()

    dropped, alive = asyncio.run(run())
    assert (dropped, alive) == (False, 1)
    assert asyncio.run(exists(name))
