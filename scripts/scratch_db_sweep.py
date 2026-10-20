"""Drops scratch databases whose run is over, on the dev PostgreSQL (`make db-sweep`; the use-case runner runs it at
start). A scratch database is attributed by its name:

    ops_usecase_r<pid>_<hex>   a use-case run (packages/usecase-runner)
    ops_test[_isolated]_r<pid>_<hex>[_<suffix>]   a make test run (make/env.mk), and the databases its suites make
                               beside it (`_conformance`)
    ops_tools_p<pid>_<hex>     the gateway ownership test (services/agents-service/tests/gateway)

One is dropped only when process <pid> is gone and no session is connected to it. Two names carry no pid:
`ops_usecase_isolated` is an isolated stack's and is never touched here, and `ops_tools_<8 hex>` (made before the test
named its pid) is dropped only when no session is connected and its files are over an hour old. Every other database
is left alone.

    uv run python scripts/scratch_db_sweep.py [--dry-run] [--url postgresql://ops:ops@localhost:5477/postgres]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import time
from typing import Any

import asyncpg  # pyright: ignore[reportMissingTypeStubs]

WITH_PID = re.compile(r"^ops_(?:usecase_r|tools_p|test_r|test_isolated_r)(?P<pid>\d+)_[0-9a-f]+(?:_[a-z_]+)?$")
LEGACY = re.compile(r"^ops_tools_[0-9a-f]{8}$")
LEGACY_AGE_S = 3600


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def sweep(url: str, dry_run: bool) -> list[str]:
    c: Any = await asyncpg.connect(url)  # pyright: ignore[reportUnknownMemberType]
    dropped: list[str] = []
    try:
        rows = await c.fetch(
            "SELECT d.datname, d.oid, "
            "(SELECT count(*) FROM pg_stat_activity a WHERE a.datname = d.datname) AS sessions "
            "FROM pg_database d WHERE d.datname LIKE 'ops\\_%'"
        )
        for r in rows:
            name, sessions = str(r["datname"]), int(r["sessions"])
            if sessions:
                continue
            m = WITH_PID.match(name)
            if m:
                if alive(int(m.group("pid"))):
                    continue
            elif LEGACY.match(name):
                modified = await c.fetchval(f"SELECT (pg_stat_file('base/{r['oid']}')).modification")
                if modified is None or time.time() - modified.timestamp() < LEGACY_AGE_S:
                    continue
            else:
                continue
            if not dry_run:
                await c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            dropped.append(name)
    finally:
        await c.close()
    return dropped


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    port = os.environ.get("OPS_PG_PORT", "5477")
    ap.add_argument("--url", default=f"postgresql://ops:ops@localhost:{port}/postgres")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    dropped = asyncio.run(sweep(a.url, a.dry_run))
    verb = "would drop" if a.dry_run else "dropped"
    print(f"db-sweep: {verb} {len(dropped)} scratch database(s) of finished runs")


if __name__ == "__main__":
    main()
