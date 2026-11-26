# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# asyncpg ships without type information.
"""Can `make up` migrate the stack's database in place? It always migrates and never drops data on its own (owner:
"Always migrate"): a chain behind this checkout's head is migrated forward, and a chain the database holds at
a revision this checkout does not have (another session's newer code, or an edited migration) stops `make up` with
the chain named and the fix, because migrating it would be guessing.

  uv run python scripts/schema_sync.py <database url>           # 0: every chain at or behind its head; 4: one ahead
  uv run python scripts/schema_sync.py <database url> --reset --confirmed-by-reset-db  # empty it (make reset-db only)
  uv run python scripts/schema_sync.py <database url> --create  # make the database when missing (OPS_INFRA=shared)
  uv run python scripts/schema_sync.py <database url> --recorded  # each chain's recorded revision, one line each

Each service keeps its own chain and version table in the one database. The reset drops the whole database rather
than one service's objects: the chains share roles, policies and functions, and their DDL runs in order only from an
empty database. The services' dev seeds fill it again when they start. Callers stop every service on the database
first; the drop uses FORCE. Only `make reset-db` (or `make up RESET=1`) calls it.
"""

from __future__ import annotations

import asyncio
import os
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
    ("kb", "services/kb-service", "alembic_version_kb"),
    ("platform", "services/platform-service", "alembic_version_platform"),
    ("files", "services/files-service", "alembic_version_files"),
    # After files: files_0006 drops the tables documents_0001 makes again on its side.
    ("documents", "services/documents-service", "alembic_version_documents"),
)
# The tests' and use cases' databases are made and dropped by their own runners.
REFUSED = ("ops_test", "ops_usecase")
# The only flag `make reset-db` passes, after its yes prompt: a reset of any other database is refused without it.
CONFIRMED = "--confirmed-by-reset-db"


def own_shared_database(name: str) -> None:
    """OPS_INFRA=shared: an offset stack's database is ops_runtime_<offset>; the default stack's ops_runtime and every
    other stack's database live in the same postgres and are never this stack's to create or drop."""
    offset = os.environ.get("OPS_PORT_OFFSET", "0")
    if os.environ.get("OPS_INFRA") == "shared" and not name.startswith(REFUSED) and name != f"ops_runtime_{offset}":
        raise SystemExit(
            f"schema_sync: refusing {name!r}: OPS_INFRA=shared stack at offset {offset} owns only ops_runtime_{offset}"
        )


def code_head(directory: str) -> str:
    heads = ScriptDirectory.from_config(Config(str(ROOT / directory / "alembic.ini"))).get_heads()
    return ",".join(sorted(heads))


def known(directory: str, version: str) -> bool:
    """Whether this checkout's chain has the revision the database records; a revision it lacks is ahead of it."""
    script = ScriptDirectory.from_config(Config(str(ROOT / directory / "alembic.ini")))
    try:
        for v in version.split(","):
            script.get_revision(v)
    except Exception:  # alembic raises its own errors for an unknown or ambiguous revision
        return False
    return True


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
            rows = await c.fetch(f"SELECT version_num FROM {table}") if exists else []  # noqa: S608
            found[table] = ",".join(sorted(str(r[0]) for r in rows)) or None
    finally:
        await c.close()
    return found


async def reset(url: str, confirmed: bool = False) -> None:
    dsn, name = _dsn(url)
    if not name:
        raise SystemExit("schema_sync: refusing to reset a database with no name")
    if not confirmed and not name.startswith(REFUSED):
        raise SystemExit(
            f"schema_sync: refusing to reset {name!r}: only make reset-db, after its yes prompt, resets it"
        )
    own_shared_database(name)
    admin = await asyncpg.connect(dsn.rsplit("/", 1)[0] + "/postgres")
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()
    print(f"schema_sync: {name} dropped and recreated empty; make migrate builds it from the chains")


async def create(url: str) -> None:
    """Make the database when it is missing; one that exists is left alone. Only an offset stack's own
    ops_runtime_<offset> on the shared postgres goes through here."""
    dsn, name = _dsn(url)
    if not name or name.startswith(REFUSED):
        raise SystemExit(f"schema_sync: refusing to create {name!r}; its runner owns it")
    own_shared_database(name)
    admin = await asyncpg.connect(dsn.rsplit("/", 1)[0] + "/postgres")
    try:
        if not await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
            await admin.execute(f'CREATE DATABASE "{name}"')
            print(f"schema_sync: created {name}")
    finally:
        await admin.close()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    url = sys.argv[1]
    if "--create" in sys.argv[2:]:
        asyncio.run(create(url))
        return 0
    if "--reset" in sys.argv[2:]:
        asyncio.run(reset(url, CONFIRMED in sys.argv[2:]))
        return 0
    db = asyncio.run(recorded(url))
    if "--recorded" in sys.argv[2:]:
        # What `stack.sh note-migrations` compares from one migrate to the next.
        print("\n".join(f"{table}={db[table] or '-'}" for _, _, table in CHAINS))
        return 0
    ahead = 0
    for service, directory, table in CHAINS:
        head, have = code_head(directory), db[table]
        if have is None or have == head:
            continue
        if known(directory, have):
            print(f"schema_sync: {service} database at {have}, code at {head}; make up migrates it forward")
            continue
        print(
            f"schema_sync: {service} database at {have}, which this checkout's chain does not have (code at {head}). "
            "It was migrated by newer code or an edited migration. Check out code that has it, or wipe the "
            "database with make reset-db."
        )
        ahead = 1
    return 4 if ahead else 0


if __name__ == "__main__":
    raise SystemExit(main())
