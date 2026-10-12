"""Creates the test database if it is missing and migrates it to head on each service's chain.

  uv run python scripts/test_db.py postgresql+asyncpg://ops:ops@localhost:5477/ops_test

The make test targets call this and run pytest with OPS_DATABASE_URL set to the same URL, so tests never share a
database with the live stack (whose timer poller would claim the tests' timers).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
CHAINS = ("services/agents-service", "services/tools-service", "services/models-service", "services/platform-service")


async def create(url: str) -> None:
    parsed = make_url(url)
    if parsed.database in (None, "ops_runtime"):
        raise SystemExit(f"test_db: refusing {parsed.database}; tests get their own database")
    admin = create_async_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with admin.connect() as c:
        found = (await c.execute(text("select 1 from pg_database where datname = :n"), {"n": parsed.database})).first()
        if found is None:
            await c.execute(text(f'create database "{parsed.database}"'))
    await admin.dispose()


def migrate(url: str) -> None:
    env = {**os.environ, "OPS_DATABASE_URL": url}
    for chain in CHAINS:
        subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"], cwd=ROOT / chain, env=env, check=True, capture_output=True
        )


if __name__ == "__main__":
    asyncio.run(create(sys.argv[1]))
    migrate(sys.argv[1])
