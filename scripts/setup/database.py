"""The database answer: our container, a PostgreSQL URL (Azure Database for PostgreSQL among them) or Azure SQL. A
PostgreSQL database must connect, run version 15 to 17, and have the row policy on for every tenant table the chains
declare (deploy/database/models.py) that it already holds. An empty database passes: the install applies the schema
with its policies. Azure SQL fails until the store runs on it (c-543, c-544)."""

from __future__ import annotations

import asyncio
import os
import urllib.parse
from typing import Any

from setup.report import Result

ITEM = "database"
VERSIONS = range(150000, 180000)
TIMEOUT_S = 10.0
CONTAINER = "builtin"


def container_url() -> str:
    """Our container as this stack reaches it: the `postgres` side container in a devcontainer (OPS_INFRA=external),
    otherwise compose's published port on this machine (make/env.mk)."""
    if os.environ.get("OPS_INFRA") == "external":
        return "postgresql://ops:ops@postgres:5432/ops_runtime"
    return f"postgresql://ops:ops@localhost:{os.environ.get('OPS_PG_PORT', '5477')}/ops_runtime"


def _password(url: str) -> str:
    return urllib.parse.unquote(urllib.parse.urlsplit(url).password or "")


def _tenant_tables() -> set[str]:
    """Every table a chain declares as isolated by tenant or team, from the store packages' own metadata."""
    # Imported here: the rest of setup is the standard library and runs before make install.
    from models import chain_metadata, chains  # noqa: PLC0415 - deploy/database, on the path make setup sets

    from ops_store.schema import tenant_scoped  # noqa: PLC0415

    return {t.name for chain in chains() for m in chain_metadata(chain) for t in m.tables.values() if tenant_scoped(t)}


async def _inspect(url: str, ssl: bool) -> tuple[int, set[str], set[str]]:
    import asyncpg  # noqa: PLC0415 - the one dependency; its absence is a FAIL that says to run make install

    conn: Any = await asyncpg.connect(url, timeout=TIMEOUT_S, ssl="require" if ssl else None)
    try:
        version = int(await conn.fetchval("SHOW server_version_num"))
        present = {
            r[0] for r in await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
        }
        isolated = {
            r[0]
            for r in await conn.fetch(
                "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
                " WHERE n.nspname = current_schema() AND c.relrowsecurity AND c.relforcerowsecurity"
            )
        }
        return version, present, isolated
    finally:
        await conn.close()


def check(answer: str) -> Result:
    answer = answer.strip()
    if answer.split(":", 1)[0] in ("mssql", "sqlserver", "azuresql") or "database.windows.net" in answer:
        return Result(ITEM, False, "Azure SQL is not supported in this version (c-543, c-544)", answer=answer)
    url = container_url() if answer == CONTAINER else answer
    parts = urllib.parse.urlsplit(url.replace("postgresql+asyncpg://", "postgresql://"))
    if parts.scheme not in ("postgresql", "postgres"):
        return Result(ITEM, False, f"not a PostgreSQL URL or {CONTAINER!r}", answer=answer)
    secrets = (_password(url),)
    plain = urllib.parse.urlunsplit(("postgresql", *parts[1:]))
    azure = (parts.hostname or "").endswith(".postgres.database.azure.com")
    where = f"{parts.hostname}:{parts.port or 5432}{parts.path}"
    try:
        version, present, isolated = asyncio.run(_inspect(plain, ssl=azure or "sslmode=require" in parts.query))
    except ImportError:
        return Result(ITEM, False, "the database driver is not installed here: run make install, then setup again")
    except Exception as e:  # any failure to connect is this item's FAIL, with the driver's reason
        return Result(ITEM, False, f"{where}: {type(e).__name__}: {e}", secrets=secrets, answer=answer)
    if version not in VERSIONS:
        return Result(ITEM, False, f"{where}: PostgreSQL {version // 10000}, not 15 to 17", secrets=secrets)
    try:
        expected = _tenant_tables() & present
    except ImportError as e:
        return Result(ITEM, False, f"the workspace is not installed here ({e.name}): run make install", secrets=secrets)
    off = sorted(expected - isolated)
    if off:
        shown = ", ".join(off[:5]) + (f" and {len(off) - 5} more" if len(off) > 5 else "")
        return Result(ITEM, False, f"{where}: row policy off on {shown}; run the migrations", secrets=secrets)
    state = f"row policy on for {len(expected)} tenant tables" if expected else "empty; the install applies the schema"
    settings = {} if answer == CONTAINER else {"OPS_DATABASE_URL": url}
    kind = "Azure Database for PostgreSQL" if azure else "PostgreSQL"
    return Result(
        ITEM, True, f"{where}: {kind} {version // 10000}, {state}", settings=settings, secrets=secrets, answer=answer
    )
