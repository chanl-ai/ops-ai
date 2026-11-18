"""Each chain's store metadata equals the schema its migrations build: one case per chain, on a scratch
PostgreSQL database that every chain migrates in order, dropped at exit. A migration that adds a table, column, index,
CHECK or default without the same in metadata fails here, naming the object, because SQL Server's DDL is compiled from
metadata and would lack it. Each table's isolation kind (team or tenant, from its markings) is held equal to what the
database enforces.

Runs on the server of OPS_TEST_DATABASE_URL (make python-verify sets it); skipped without a PostgreSQL URL."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine

from ops_store.schema import differences, unowned

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mssql
from models import EXCLUDED, chain_metadata, chains

ROOT = Path(__file__).resolve().parents[3]
# Known differences whose fix is another change, by chain. Held exactly: a case fails on any other difference and on
# one of these no longer found, so the entry comes off in the commit that fixes it.
LAGGING: dict[str, set[str]] = {
    # tools migration 0026 gave the outbox's attempts a database default that files' and documents' outboxes lack, and
    # ops_store.outbox_table is one shape for all three; a migration makes them one.
    "tools": {"default service_outbox.attempts only in the database"},
}


def _server() -> URL:
    raw = os.environ.get("OPS_TEST_DATABASE_URL", "")
    if not raw.startswith("postgresql"):
        pytest.skip("parity runs on PostgreSQL; set OPS_TEST_DATABASE_URL")
    return make_url(raw)


async def _admin(server: URL, sql: str) -> None:
    engine = create_async_engine(server.set(database="postgres"), isolation_level="AUTOCOMMIT")
    async with engine.connect() as c:
        await c.execute(sa.text(sql))
    await engine.dispose()


@pytest.fixture(scope="module")
def scratch() -> Iterator[URL]:
    server = _server()
    url = server.set(database=f"{server.database}_parity")
    drop = f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'
    asyncio.run(_admin(server, drop))
    asyncio.run(_admin(server, f'CREATE DATABASE "{url.database}"'))
    env = {**os.environ, "OPS_DATABASE_URL": url.render_as_string(hide_password=False)}
    try:
        for chain in chains():
            done = subprocess.run(
                ["uv", "run", "alembic", "upgrade", "head"],
                check=False,
                cwd=ROOT / "services" / f"{chain}-service",
                env=env,
                capture_output=True,
                text=True,
            )
            assert done.returncode == 0, f"{chain} did not migrate: {done.stderr[-2000:]}"
        yield url
    finally:
        asyncio.run(_admin(server, drop))


def _run[T](url: URL, check: Callable[[sa.Connection], T]) -> T:
    async def go() -> T:
        engine = create_async_engine(url)
        try:
            async with engine.connect() as c:
                return await c.run_sync(check)
        finally:
            await engine.dispose()

    return asyncio.run(go())


@pytest.mark.parametrize("chain", chains())
def test_the_chain_s_metadata_is_its_migrated_schema(scratch: URL, chain: str) -> None:
    found = set(_run(scratch, lambda c: differences(c, chain_metadata(chain), EXCLUDED.get(chain, ()))))
    lagging = LAGGING.get(chain, set())
    assert found - lagging == set(), f"{chain}: metadata and migrations differ:\n" + "\n".join(sorted(found - lagging))
    assert lagging - found == set(), f"{chain}: fixed, take these off LAGGING: {sorted(lagging - found)}"


def test_every_table_belongs_to_a_chain_s_metadata(scratch: URL) -> None:
    every = [m for chain in chains() for m in chain_metadata(chain)]
    excluded = {t for names in EXCLUDED.values() for t in names}
    assert _run(scratch, lambda c: unowned(c, every, excluded)) == []


HAND_MADE = {
    "column": "ALTER TABLE files ADD COLUMN hand_made varchar(10)",
    "index": "CREATE INDEX ix_hand_made ON files (tenant_id)",
    "check": "ALTER TABLE files ADD CONSTRAINT ck_hand_made CHECK (length(id) > 0)",
    # Every files table is isolated, so the hand-made change takes one table's forced isolation away.
    "isolation": "ALTER TABLE files_outbox NO FORCE ROW LEVEL SECURITY",
}


@pytest.mark.parametrize("kind", sorted(HAND_MADE))
def test_a_change_made_by_hand_fails_the_owning_chain(scratch: URL, kind: str) -> None:
    def check(c: sa.Connection) -> list[str]:
        # Inside a transaction that is rolled back, so the scratch schema is unchanged for the other cases.
        with c.begin() as tx:
            for statement in HAND_MADE[kind].split("; "):
                c.execute(sa.text(statement))
            found = differences(c, chain_metadata("files"))
            tx.rollback()
        return found

    found = _run(scratch, check)
    assert any("files" in line for line in found), f"{kind} made by hand went unseen: {found}"


@pytest.mark.parametrize("chain", sorted(mssql.SYSTEM_USERS))
def test_the_sql_server_system_principal_reads_what_postgresql_s_system_role_reads(scratch: URL, chain: str) -> None:
    """mssql.SYSTEM_USERS restates each chain's migrations' grants to its BYPASSRLS role; this holds the two equal."""
    user, reads = mssql.SYSTEM_USERS[chain]

    def grants(c: sa.Connection) -> list[tuple[str, str, str | None]]:
        q = """SELECT table_name, privilege_type, NULL FROM information_schema.role_table_grants
               WHERE grantee = :u
               UNION ALL
               SELECT table_name, privilege_type, column_name FROM information_schema.column_privileges
               WHERE grantee = :u"""
        return [(str(t), str(p), col) for t, p, col in c.execute(sa.text(q), {"u": user})]

    found = _run(scratch, grants)
    whole = {(t, p) for t, p, col in found if col is None}
    # column_privileges also lists every column of a table-wide grant; only a grant narrower than its table counts.
    on_pg = {(t, p, "") for t, p in whole} | {(t, p, str(col)) for t, p, col in found if col and (t, p) not in whole}
    declared = {
        (t, p, col) for t, (privileges, columns) in reads.items() for p in privileges for col in (columns or ("",))
    }
    assert on_pg == declared


# The role each chain's transactions switch to on PostgreSQL; on SQL Server its runtime user stands for it.
TENANT_ROLES = {
    "agents": "ops_runtime_tenant",
    "tools": "ops_tools_tenant",
    "models": "ops_models_tenant",
    "kb": "ops_kb_tenant",
    "platform": "ops_platform_tenant",
    "files": "ops_files_tenant",
    "documents": "ops_documents_tenant",
}
# Tables a store with no role writes as the service's login, which grants.sql gives DML on every table of its chain;
# the tenant role holds none of them, so the runtime user keeps DML (ops_models.store: Aliases, KeySpend, ModelKeys,
# Providers).
AS_THE_LOGIN = {
    "models": {"model_aliases", "model_calls_untenanted", "model_key_spend", "model_keys", "provider_connections"}
}


@pytest.mark.parametrize("chain", chains())
def test_the_sql_server_runtime_user_holds_what_postgresql_s_tenant_role_holds(scratch: URL, chain: str) -> None:
    """A table-wide or column grant the tenant role lacks is one the runtime user lacks, so a statement PostgreSQL
    refuses a tenant's transaction SQL Server refuses too."""
    role = TENANT_ROLES[chain]

    def held(c: sa.Connection) -> list[tuple[str, str, str]]:
        q = """SELECT t.table_name, p.p, '' FROM information_schema.tables t
                 CROSS JOIN (VALUES ('SELECT'), ('INSERT'), ('UPDATE'), ('DELETE')) p(p)
               WHERE t.table_schema = 'public' AND has_table_privilege(:r, 'public.' || t.table_name, p.p)
               UNION ALL
               SELECT table_name, privilege_type, column_name FROM information_schema.column_privileges
               WHERE grantee = :r AND table_schema = 'public'"""
        return [(str(t), str(p), str(col)) for t, p, col in c.execute(sa.text(q), {"r": role})]

    found = _run(scratch, held)
    whole = {(t, p) for t, p, col in found if not col}
    on_sql_server = [t.name for t in mssql.chain_tables(chain, chain_metadata(chain)).tables]
    login = AS_THE_LOGIN.get(chain, set())
    on_pg = {(t, p, "") for t, p in whole if t in on_sql_server and t not in login} | {
        (t, p, col) for t, p, col in found if col and (t, p) not in whole and t in on_sql_server
    }
    declared = {
        (t, p, col)
        for t in on_sql_server
        if t not in login
        for privileges, columns in [mssql.runtime_grants(chain, t)]
        for p, col in [*((p, "") for p in privileges), *(("UPDATE", c) for c in columns)]
    }
    assert on_pg - declared == set(), f"{chain}: PostgreSQL's tenant role holds more: {sorted(on_pg - declared)}"
    assert declared - on_pg == set(), f"{chain}: the SQL Server runtime user holds more: {sorted(declared - on_pg)}"
    assert all(mssql.runtime_grants(chain, t) == (mssql.DML, ()) for t in login)
