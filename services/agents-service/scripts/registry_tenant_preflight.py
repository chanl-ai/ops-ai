"""Before migration 0106, which gives the registry and deployment tables a tenant: lists what it cannot place.

Outside dev the migration stops on a team seen in no tenant, a team seen in two or more tenants other than `local`,
and a record referenced from two or more tenants other than `local`; this lists each, by the same statements
(`ops_agents.store.registry_tenants`). Exits 1 when any exists, 0 when none does, 2 when the database cannot be read
across tenants without changing a security policy (SQL Server), with what to run instead. It writes nothing.

  make -C services/agents-service registry-tenant-preflight     (the database is OPS_DATABASE_URL, as for migrations)
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.store.registry_tenants import PreflightRefused, gaps
from ops_service_kit.settings import Settings


async def main() -> int:
    engine = create_async_engine(Settings().database_url)
    try:
        found = await gaps(engine)
    except PreflightRefused as e:
        print(e, file=sys.stderr)
        return 2
    finally:
        await engine.dispose()
    lines = found.lines()
    print("\n".join(lines or ["every registry and deployment row has one tenant to take"]))
    return 1 if lines else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
