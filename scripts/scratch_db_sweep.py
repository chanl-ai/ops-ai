"""Drops scratch databases whose run is over, on the dev PostgreSQL (`make db-sweep`; the use-case runner runs it at
start). A scratch database is attributed by its name:

    ops_usecase_r<pid>_<hex>   a use-case run (packages/usecase-runner)
    ops_test[_isolated]_r<pid>_<hex>[_<suffix>]   a make test run (make/env.mk), its workers' copies (`_gw<k>`), and
                               the databases its suites make beside it (`_conformance`)
    ops_tools_p<pid>_<hex>     the gateway ownership test (services/agents-service/tests/gateway)
    ops_test_mssql_<hex>       a SQL Server test run's PostgreSQL database (deploy/database/mssql_local.sh)

One is dropped only when process <pid> is gone, no session is connected to it, and none of its files has changed for
an hour: the pid can exit while its run goes on (a run started under a parent that returned), and a run between two
tests holds no session, so the files are what show it is still writing. The drop does not force: a session that
connects after the sweep looked makes the drop fail and the database stays. Two names carry no pid:
`ops_usecase_isolated` is an isolated stack's and is never touched here, and `ops_tools_<8 hex>` (made before the test
named its pid) and `ops_test_mssql_<hex>` are dropped on the same no-session and quiet-files rules. The QA runner's
databases
(`ops_test_head_<pid>`, scripts/verify-head.sh) belong to it alone, which drops them at exit. Every other database is
left alone.

    uv run python scripts/scratch_db_sweep.py [--dry-run] [--url postgresql://ops:ops@localhost:5477/postgres]

`--prune [--hours N] [--prefix P ...]` (`make test-db-prune`) is the net under the sweep for what no pid explains: it
drops every `ops_test_*` and `ops_usecase_*` database (or those starting with each --prefix) that has no session and was
created more than N hours ago (default 3; the age of its PG_VERSION file), and prints the count and bytes freed. Never
`ops_test` itself or `ops_usecase_isolated`. `--drop NAME` drops one such database now (a run's own cleanup).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import time
from typing import Any
from urllib.parse import urlsplit

import asyncpg  # pyright: ignore[reportMissingTypeStubs]

WITH_PID = re.compile(r"^ops_(?:usecase_r|tools_p|test_r|test_isolated_r)(?P<pid>\d+)_[0-9a-f]+(?:_[a-z0-9_]+)?$")
# Names made without a pid: the gateway test's first form, and a mssql_local.sh run's PostgreSQL database.
LEGACY = re.compile(r"^ops_(?:tools_[0-9a-f]{8}|test_mssql_[0-9a-f]{6})$")
# The QA runner's export database and the ones its suites make beside it; never this sweep's to drop.
RUNNER_OWNED = "ops_test_head_"
# How long a database's files must be unchanged before it counts as finished.
QUIET_S = 3600


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def last_write(c: Any, oid: int) -> float | None:
    """When any file of the database last changed: its folder changes when a table is made or dropped, its files on
    every write."""
    return await c.fetchval(
        "SELECT extract(epoch FROM max(m)) FROM ("
        "  SELECT (pg_stat_file('base/' || $1::text)).modification AS m"
        "  UNION ALL SELECT (pg_stat_file('base/' || $1::text || '/' || f)).modification"
        "  FROM pg_ls_dir('base/' || $1::text) AS f"
        ") AS t",
        str(oid),
    )


async def drop(c: Any, name: str) -> bool:
    """Drops `name` unless a session holds it; False when one does."""
    try:
        await c.execute(f'DROP DATABASE IF EXISTS "{name}"')
    except asyncpg.ObjectInUseError:
        return False
    return True


async def sweep(url: str, dry_run: bool, now: float | None = None) -> list[str]:
    c: Any = await asyncpg.connect(url)  # pyright: ignore[reportUnknownMemberType]
    dropped: list[str] = []
    now = time.time() if now is None else now
    try:
        rows = await c.fetch(
            "SELECT d.datname, d.oid, "
            "(SELECT count(*) FROM pg_stat_activity a WHERE a.datname = d.datname) AS sessions "
            "FROM pg_database d WHERE d.datname LIKE 'ops\\_%'"
        )
        for r in rows:
            name, sessions = str(r["datname"]), int(r["sessions"])
            if sessions or name.startswith(RUNNER_OWNED):
                continue
            m = WITH_PID.match(name)
            if (m and alive(int(m.group("pid")))) or not (m or LEGACY.match(name)):
                continue
            written = await last_write(c, int(r["oid"]))
            if written is None or now - float(written) < QUIET_S:
                continue
            if dry_run or await drop(c, name):
                dropped.append(name)
    finally:
        await c.close()
    return dropped


PRUNE_PREFIXES = ("ops_test_", "ops_usecase_")
# Never pruned: the base test database and an isolated stack's.
PRUNE_KEEP = ("ops_test", "ops_usecase_isolated")


async def prune(
    url: str, hours: float = 3, prefixes: tuple[str, ...] = PRUNE_PREFIXES, dry_run: bool = False
) -> tuple[list[str], int]:
    """Drops idle databases starting with a prefix that were created over `hours` ago; returns names and bytes freed."""
    c: Any = await asyncpg.connect(url)  # pyright: ignore[reportUnknownMemberType]
    dropped: list[str] = []
    freed = 0
    try:
        rows = await c.fetch(
            "SELECT d.datname, pg_database_size(d.oid) AS bytes, "
            "extract(epoch FROM (pg_stat_file('base/' || d.oid || '/PG_VERSION')).modification) AS made, "
            "(SELECT count(*) FROM pg_stat_activity a WHERE a.datname = d.datname) AS sessions "
            "FROM pg_database d WHERE NOT d.datistemplate"
        )
        now = time.time()
        for r in rows:
            name = str(r["datname"])
            if name in PRUNE_KEEP or not name.startswith(prefixes) or r["sessions"]:
                continue
            if r["made"] is None or now - float(r["made"]) < hours * 3600:
                continue
            if dry_run or await drop(c, name):
                dropped.append(name)
                freed += int(r["bytes"])
    finally:
        await c.close()
    return dropped, freed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    # make/env.mk's rule: the devcontainer's side container (OPS_INFRA=external), else compose on OPS_PG_PORT.
    if os.environ.get("OPS_INFRA") == "external":
        # The host and port OPS_DATABASE_URL names: `postgres:5432` in the devcontainer, `localhost:5477` hosted.
        netloc = urlsplit(os.environ.get("OPS_DATABASE_URL", "")).netloc.rpartition("@")[2] or "postgres:5432"
        default = f"postgresql://ops:ops@{netloc}/postgres"
    else:
        default = f"postgresql://ops:ops@localhost:{os.environ.get('OPS_PG_PORT', '5477')}/postgres"
    ap.add_argument("--url", default=default)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--prune", action="store_true")
    ap.add_argument("--hours", type=float, default=3)
    ap.add_argument("--prefix", action="append")
    ap.add_argument("--drop", metavar="NAME")
    a = ap.parse_args()
    if a.drop:
        if not a.drop.startswith(PRUNE_PREFIXES) or a.drop in PRUNE_KEEP:
            raise SystemExit(f"db-sweep: refusing to drop {a.drop}")

        async def one() -> None:
            c: Any = await asyncpg.connect(a.url)  # pyright: ignore[reportUnknownMemberType]
            try:
                await c.execute(f'DROP DATABASE IF EXISTS "{a.drop}" WITH (FORCE)')
            finally:
                await c.close()

        asyncio.run(one())
        return
    if a.prune:
        names, freed = asyncio.run(prune(a.url, a.hours, tuple(a.prefix or PRUNE_PREFIXES), a.dry_run))
        verb = "would drop" if a.dry_run else "dropped"
        print(f"test-db-prune: {verb} {len(names)} database(s), {freed / 1e6:.1f} MB")
        return
    dropped = asyncio.run(sweep(a.url, a.dry_run))
    verb = "would drop" if a.dry_run else "dropped"
    print(f"db-sweep: {verb} {len(dropped)} scratch database(s) of finished runs")


if __name__ == "__main__":
    main()
