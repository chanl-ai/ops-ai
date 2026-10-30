# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false
# asyncpg ships without type information.
"""Makes a named use-case database match this checkout's migration chains before a run uses it: when any chain it
records differs from the chain's head, it is dropped and made again empty, and the scripts' services migrate and seed
it as on first use. A use-case database is scratch the runner owns, and migrating one in place can fail: no migration
rewrites rows, so a row an older chain allowed and the newer one refuses (tools_0012 refuses money_movement operations)
stops every script at start. `make up` keeps the stack's own database and migrates it in place (scripts/schema_sync.py);
this is only for use-case databases, so it refuses any other name.

    uv run python docs/usecases/lib/usecase_db.py <database url>     prints what it rebuilt, or nothing; exit 0

The runner calls it once per run for a database the caller named (OPS_USECASE_DB); a database the run names itself is
new and needs nothing."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import asyncpg

ROOT = Path(__file__).resolve().parents[3]
PREFIX = "ops_usecase"


def _schema_sync() -> ModuleType:
    """scripts/schema_sync.py, whose chains and heads `make up` checks: the one list of chains."""
    spec = importlib.util.spec_from_file_location("schema_sync", ROOT / "scripts" / "schema_sync.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _dsn(url: str) -> tuple[str, str]:
    plain = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return plain, plain.rsplit("/", 1)[1]


def stale(url: str) -> list[str]:
    """Each chain the database records at a revision other than this checkout's head, as `<chain> at <have>, code at
    <head>`. A database that does not exist, or a chain it has not started, is not stale: its services migrate it."""
    sync = _schema_sync()
    recorded: dict[str, str | None] = asyncio.run(sync.recorded(url))
    out: list[str] = []
    for service, directory, table in sync.CHAINS:
        have, head = recorded[table], sync.code_head(directory)
        if have is not None and have != head:
            out.append(f"{service} at {have}, code at {head}")
    return out


async def _recreate(url: str) -> None:
    dsn, name = _dsn(url)
    admin = await asyncpg.connect(dsn.rsplit("/", 1)[0] + "/postgres")
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()


def rebuild_if_stale(url: str) -> list[str]:
    """Drops and recreates the database when a chain is stale; returns the stale chains (none: nothing was done)."""
    name = _dsn(url)[1]
    if not name.startswith(PREFIX):
        raise SystemExit(f"usecase-db: refusing {name!r}: only use-case databases ({PREFIX}*) are rebuilt here")
    found = stale(url)
    if found:
        asyncio.run(_recreate(url))
    return found


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    url = sys.argv[1]
    found = rebuild_if_stale(url)
    if found:
        print(f"usecase-db: {_dsn(url)[1]} rebuilt empty ({'; '.join(found)}); the scripts migrate and seed it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
