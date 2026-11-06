"""Creates the test database if it is missing and migrates it to head on each service's chain. A test database whose
recorded versions are not this checkout's heads was built by other code, so it is dropped and built again: its rows
are test data, and a migration that adds a constraint (tools_0012's CHECK on access) fails on rows the old code
wrote. The rule is `make up`'s for the stack database (scripts/schema_sync.py).

  uv run python scripts/test_db.py postgresql+asyncpg://ops:ops@localhost:5477/ops_test_r123_ab12cd

Before it creates one, it drops the test databases of runs that are over (scripts/scratch_db_sweep.py), since each make
run names its own (make/env.mk).

The make test targets call this and run pytest with OPS_DATABASE_URL set to the same URL, so tests never share a
database with the live stack (whose timer poller would claim the tests' timers).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from schema_sync import CHAINS as VERSION_TABLES
from schema_sync import code_head, recorded
from scratch_db_sweep import sweep
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
CHAINS = ("services/agents-service", "services/tools-service", "services/models-service", "services/platform-service")


async def create(url: str) -> None:
    parsed = make_url(url)
    if parsed.database in (None, "ops_runtime"):
        raise SystemExit(f"test_db: refusing {parsed.database}; tests get their own database")
    have = await recorded(url)
    stale = [
        f"{service} at {have[table] or 'nothing'}, code at {code_head(directory)}"
        for service, directory, table in VERSION_TABLES
        if have[table] is not None and have[table] != code_head(directory)
    ]
    admin = create_async_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as c:
        if stale:
            print(f"test_db: rebuilding {parsed.database}: {'; '.join(stale)}", file=sys.stderr)
            await c.execute(text(f'drop database if exists "{parsed.database}" with (force)'))
        found = (await c.execute(text("select 1 from pg_database where datname = :n"), {"n": parsed.database})).first()
        if found is None:
            await c.execute(text(f'create database "{parsed.database}"'))
    await admin.dispose()


# Roles are server-wide, and the chains create theirs with `CREATE ROLE ... EXCEPTION WHEN duplicate_object`, which
# does not catch the unique_violation a second session gets while another session's CREATE ROLE is uncommitted. Two
# test databases migrating at once on a fresh server (make verify runs its suites in parallel) fail on it, so a server
# migrates one test database at a time. Advisory locks are scoped to a database, so every caller takes it in `postgres`.
MIGRATE_LOCK = 0x6F70735F


async def migrate(url: str) -> None:
    env = {**os.environ, "OPS_DATABASE_URL": url}
    admin = create_async_engine(make_url(url).set(database="postgres"))
    try:
        async with admin.connect() as c:
            await c.execute(text("select pg_advisory_lock(:k)"), {"k": MIGRATE_LOCK})
            for chain in CHAINS:
                run = subprocess.run(
                    ["uv", "run", "alembic", "upgrade", "head"],
                    cwd=ROOT / chain,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if run.returncode:
                    sys.stderr.write(run.stderr[-4000:])
                    raise SystemExit(f"test_db: alembic upgrade head failed in {chain} on {make_url(url).database}")
    finally:
        # Closing the session releases the lock, on success or failure.
        await admin.dispose()


if __name__ == "__main__":
    server = make_url(sys.argv[1]).set(drivername="postgresql", database="postgres")
    asyncio.run(sweep(server.render_as_string(hide_password=False), dry_run=False))
    asyncio.run(create(sys.argv[1]))
    asyncio.run(migrate(sys.argv[1]))
