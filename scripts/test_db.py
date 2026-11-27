"""Creates the test database if it is missing and migrates it to head on each service's chain. A test database whose
recorded versions are not this checkout's heads was built by other code, so it is dropped and built again: its rows
are test data, and a migration that adds a constraint (tools_0012's CHECK on access) fails on rows the old code
wrote. The rule is `make up`'s for the stack database (scripts/schema_sync.py).

  uv run python scripts/test_db.py postgresql+asyncpg://ops:ops@localhost:5477/ops_test_r123 [--workers N] [--service S]

A new test database is a clone, `CREATE DATABASE ... TEMPLATE`, of a template that holds the chains migrated once:
`ops_tpl_<service>_<hash>`, where the hash covers the service's chains (the four every suite needs, plus its own for
kb, files and documents), their store code and ops_store, ops_service_kit and ops_engine. A clone takes a fraction of a
second where migrating the chains took tens of seconds. The template is built again only when that hash changes, and
the ones with an older hash are dropped. OPS_TEST_TEMPLATE=0 migrates each database as before. A database that already
exists (a caller named one) is checked and migrated in place, as before.

With --workers N (a parallel run, `make test PAR=N`) it also makes N copies of the migrated database, `<name>_gw0` to
`<name>_gw<N-1>`, one per pytest-xdist worker (ops_service_kit.testdb.use_worker_database). A copy is a template clone,
a fraction of a second, where migrating each would take the chains' full time again.

Before it creates one, it drops the test databases of runs that are over (scripts/scratch_db_sweep.py), since each make
run names its own (make/env.mk).

The make test targets call this and run pytest with OPS_DATABASE_URL set to the same URL, so tests never share a
database with the live stack (whose timer poller would claim the tests' timers).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

from schema_sync import CHAINS as VERSION_TABLES
from schema_sync import code_head, recorded
from scratch_db_sweep import sweep
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
CHAINS = ("services/agents-service", "services/tools-service", "services/models-service", "services/platform-service")
# Code a migration imports besides its own folder (env.py reads each service's store metadata).
SHARED_CODE = ("packages/ops_store/src", "packages/ops_service_kit/src", "packages/ops_engine/src")


def chains_for(service: str | None) -> tuple[str, ...]:
    """The chains a suite's database needs: the four every suite migrates, then the service's own."""
    own = f"services/{service}" if service else None
    extra = [d for _, d, _ in VERSION_TABLES if d == own and d not in CHAINS]
    return (*CHAINS, *extra)


def template_name(chains: tuple[str, ...]) -> str:
    """ops_tpl_<own chain|base>_<hash of every file whose change can change what the migrated chains build>."""
    digest = hashlib.sha256()
    folders = [ROOT / d / "migrations" for d in chains] + [ROOT / d / "alembic.ini" for d in chains]
    folders += [p for d in chains for p in (ROOT / d / "src").glob("*/store")] + [ROOT / c for c in SHARED_CODE]
    for folder in sorted(folders):
        files = [folder] if folder.is_file() else sorted(folder.rglob("*.py")) + sorted(folder.rglob("*.mako"))
        for f in files:
            if "__pycache__" not in f.parts:
                digest.update(str(f.relative_to(ROOT)).encode() + b"\0" + f.read_bytes() + b"\0")
    extra = chains[len(CHAINS) :]
    label = Path(extra[0]).name.replace("-service", "") if extra else "base"
    return f"ops_tpl_{label}_{digest.hexdigest()[:12]}"


async def create(url: str) -> None:
    parsed = make_url(url)
    if parsed.database is None or parsed.database.startswith("ops_runtime"):
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


def upgrade_chains(url: str, chains: tuple[str, ...]) -> None:
    env = {**os.environ, "OPS_DATABASE_URL": url}
    for chain in chains:
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


async def migrate(url: str, chains: tuple[str, ...] = CHAINS) -> None:
    admin = create_async_engine(make_url(url).set(database="postgres"))
    try:
        async with admin.connect() as c:
            await c.execute(text("select pg_advisory_lock(:k)"), {"k": MIGRATE_LOCK})
            upgrade_chains(url, chains)
    finally:
        # Closing the session releases the lock, on success or failure.
        await admin.dispose()


async def clone(url: str, service: str | None) -> bool:
    """Make the test database from the service's template, building the template first when it is missing. False
    when the database already exists, which the caller then checks and migrates in place."""
    parsed = make_url(url)
    if parsed.database is None or parsed.database.startswith("ops_runtime"):
        raise SystemExit(f"test_db: refusing {parsed.database}; tests get their own database")
    chains = chains_for(service)
    tpl = template_name(chains)
    prefix = tpl.rsplit("_", 1)[0]
    admin = create_async_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as c:
            exists = "select 1 from pg_database where datname = :n"
            if (await c.execute(text(exists), {"n": parsed.database})).first() is not None:
                return False
            # One lock for building and cloning: it also keeps two runs from building the same template at once.
            await c.execute(text("select pg_advisory_lock(:k)"), {"k": MIGRATE_LOCK})
            if (await c.execute(text(exists), {"n": tpl})).first() is None:
                started = time.monotonic()
                building = f"{tpl}_b{os.getpid()}"
                await c.execute(text(f'drop database if exists "{building}" with (force)'))
                await c.execute(text(f'create database "{building}"'))
                await asyncio.to_thread(
                    upgrade_chains, parsed.set(database=building).render_as_string(hide_password=False), chains
                )
                await c.execute(text(f'alter database "{building}" rename to "{tpl}"'))
                stale = (
                    await c.execute(
                        text("select datname from pg_database where datname like :p"), {"p": f"{prefix}\\_%"}
                    )
                ).all()
                for (name,) in stale:
                    if name != tpl:
                        await c.execute(text(f'drop database if exists "{name}" with (force)'))
                print(f"test_db: built template {tpl} in {time.monotonic() - started:.0f}s", file=sys.stderr)
            await c.execute(text(f'create database "{parsed.database}" template "{tpl}"'))
    finally:
        await admin.dispose()  # closing the session releases the lock
    return True


async def copies(url: str, workers: int) -> None:
    """One copy of the migrated database per worker, made again each run so no copy holds an earlier run's rows."""
    parsed = make_url(url)
    admin = create_async_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as c:
            for k in range(workers):
                name = f"{parsed.database}_gw{k}"
                await c.execute(text(f'drop database if exists "{name}" with (force)'))
                await c.execute(text(f'create database "{name}" template "{parsed.database}"'))
    finally:
        await admin.dispose()


if __name__ == "__main__":
    args = sys.argv[1:]
    workers = int(args[args.index("--workers") + 1]) if "--workers" in args else 0
    service = args[args.index("--service") + 1] if "--service" in args else None
    target = args[0]
    server = make_url(target).set(drivername="postgresql", database="postgres")
    asyncio.run(sweep(server.render_as_string(hide_password=False), dry_run=False))
    cloned = os.environ.get("OPS_TEST_TEMPLATE") != "0" and asyncio.run(clone(target, service))
    if not cloned:
        asyncio.run(create(target))
        asyncio.run(migrate(target, chains_for(service)))
    if workers:
        asyncio.run(copies(target, workers))
