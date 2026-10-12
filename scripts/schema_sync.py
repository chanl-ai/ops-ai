# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# asyncpg ships without type information.
"""Does the stack's database hold the schema this checkout's code creates? Before launch there is no data to keep, so
`make up` rebuilds the database from the migration chains whenever it does not (owner decision); `KEEP_DATA=1`
migrates in place instead.

  uv run python scripts/schema_sync.py <database url>           # exit 0: every chain at its head; 3: one differs
  uv run python scripts/schema_sync.py <database url> --reset   # drop and recreate the database, empty

Each service keeps its own chain and version table in the one database. A chain whose recorded version is not this
checkout's head (behind, ahead from another session's newer code, or missing) means the database was not built by
this code. The reset drops the whole database rather than one service's objects: the chains share roles, policies
and functions, and their DDL runs in order only from an empty database. The services' dev seeds fill it again when
they start. Callers stop every service on the database first; the drop uses FORCE.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import urlsplit

import asyncpg
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]
# (service, directory, version table) in the order `make migrate` applies them.
CHAINS = (
    ("agents", "services/agents-service", "alembic_version"),
    ("tools", "services/tools-service", "alembic_version_tools"),
    ("models", "services/models-service", "alembic_version_models"),
    ("platform", "services/platform-service", "alembic_version_platform"),
)
# The tests' and use cases' databases are made and dropped by their own runners.
REFUSED = ("ops_test", "ops_usecase")


def code_head(directory: str) -> str:
    heads = ScriptDirectory.from_config(Config(str(ROOT / directory / "alembic.ini"))).get_heads()
    return ",".join(sorted(heads))


def _dsn(url: str) -> tuple[str, str]:
    """(an asyncpg DSN for `url`, the database name)."""
    plain = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return plain, urlsplit(plain).path.lstrip("/")


async def recorded(url: str) -> dict[str, str | None]:
    dsn, _ = _dsn(url)
    found: dict[str, str | None] = {}
    try:
        c = await asyncpg.connect(dsn)
    except asyncpg.InvalidCatalogNameError:
        return {table: None for _, _, table in CHAINS}
    try:
        for _, _, table in CHAINS:
            exists = await c.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{table}")
            rows = await c.fetch(f"SELECT version_num FROM {table}") if exists else []
            found[table] = ",".join(sorted(str(r[0]) for r in rows)) or None
    finally:
        await c.close()
    return found


async def reset(url: str) -> None:
    dsn, name = _dsn(url)
    if not name or name.startswith(REFUSED):
        raise SystemExit(f"schema_sync: refusing to reset {name!r}; its runner owns it")
    admin = await asyncpg.connect(dsn.rsplit("/", 1)[0] + "/postgres")
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    print(f"schema_sync: {name} dropped and recreated empty; make migrate builds it from the chains")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    url = sys.argv[1]
    if "--reset" in sys.argv[2:]:
        asyncio.run(reset(url))
        return 0
    db = asyncio.run(recorded(url))
    differ = 0
    for service, directory, table in CHAINS:
        head, have = code_head(directory), db[table]
        if have != head:
            print(f"schema_sync: {service} database at {have or 'nothing'}, code at {head}")
            differ = 1
    return 3 if differ else 0


if __name__ == "__main__":
    raise SystemExit(main())
