"""Before the migration that gives the registry and deployment tables a tenant: lists the teams it cannot place.

A registry or deployment row with no direct reference takes the one tenant its team is seen in. A team seen in no
tenant leaves its rows unplaced, which the migration refuses outside dev; a team seen in two or more tenants stops it
everywhere. Exits 1 when either exists, 0 when none does. Reads only: every statement runs in one transaction that is
rolled back, including SQL Server's policy drops, which a read of every tenant's rows needs there.

  make -C services/agents-service registry-tenant-preflight     (the database is OPS_DATABASE_URL, as for migrations)
"""

from __future__ import annotations

import asyncio
import sys
from collections import defaultdict

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.store.registry_tenants import every_tenant, two_tenant_teams, unmapped_teams
from ops_service_kit.settings import Settings


async def gaps(url: str | sa.URL) -> tuple[list[tuple[str, str, int]], dict[str, list[str]]]:
    """(unmapped rows by team and table, tenants of each team seen in two or more)."""
    engine = create_async_engine(url)
    try:
        async with engine.connect() as c:
            tx = await c.begin()
            try:
                before, _after = every_tenant(c.dialect.name)
                for statement in before:
                    await c.execute(sa.text(statement))
                unmapped = [(r.team_id, r.source, int(r.rows)) for r in await c.execute(unmapped_teams())]
                shared: dict[str, list[str]] = defaultdict(list)
                for r in await c.execute(two_tenant_teams()):
                    shared[r.team_id].append(r.tenant_id)
            finally:
                await tx.rollback()
    finally:
        await engine.dispose()
    return unmapped, dict(shared)


def report(unmapped: list[tuple[str, str, int]], shared: dict[str, list[str]]) -> list[str]:
    lines = [f"no tenant: team {team} holds {rows} row(s) in {source}" for team, source, rows in unmapped]
    lines += [f"two tenants: team {team} is in {len(ts)} tenants: {', '.join(ts)}" for team, ts in shared.items()]
    return lines or ["every team the registry and deployment rows need maps to one tenant"]


async def main() -> int:
    unmapped, shared = await gaps(Settings().database_url)
    for line in report(unmapped, shared):
        print(line)
    return 1 if unmapped or shared else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
