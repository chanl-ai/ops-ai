"""The database holds files-service's tables to the caller's tenant and team (c-415, migration files_0011), with raw
SQL and no WHERE clause as ops_files_tenant, by failure mode: a team transaction reading or writing another team's
file, blob, version, reference, hold or read request; a transaction reading or changing another tenant's upload keys,
storage settings or outbox events; a dropped policy that nobody notices; and the relay's system role reaching any
table but its outbox. On the PostgreSQL test database migrated to head."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_files.store import metadata
from ops_files.store.files import ROLE, SYSTEM_ROLE, files, service_outbox
from ops_store.conformance import isolation_suite
from ops_store.schema import isolation_ddl, isolation_kind

TABLES = [t for t in metadata.sorted_tables if isolation_kind(t) in ("team", "tenant")]


def test_every_files_table_is_marked() -> None:
    assert {t.name for t in metadata.sorted_tables} == {t.name for t in TABLES}


async def test_each_table_holds_a_team_or_a_tenant_to_its_rows(engine: AsyncEngine) -> None:
    assert await isolation_suite(engine, TABLES, role=ROLE) == []


async def test_a_dropped_policy_fails_the_suite_naming_its_table(engine: AsyncEngine) -> None:
    async with engine.begin() as c:
        await c.execute(sa.text("DROP POLICY files_isolation ON files"))
    try:
        failures = await isolation_suite(engine, TABLES, role=ROLE)
    finally:
        async with engine.begin() as c:
            for statement in isolation_ddl(files, "postgresql"):
                await c.execute(sa.text(statement))
    assert failures and {f.split(":")[0] for f in failures} == {"files"}, failures


async def test_the_relay_role_reads_and_marks_its_outbox_and_nothing_else(engine: AsyncEngine) -> None:
    async with engine.begin() as c:
        await c.execute(sa.text(f"SET LOCAL ROLE {SYSTEM_ROLE}"))
        await c.execute(sa.select(sa.func.count()).select_from(service_outbox))
        await c.execute(service_outbox.update().where(sa.false()).values(attempts=0))
    for table in TABLES:
        if table.name == service_outbox.name:
            continue
        with pytest.raises(ProgrammingError, match="permission denied"):
            async with engine.begin() as c:
                await c.execute(sa.text(f"SET LOCAL ROLE {SYSTEM_ROLE}"))
                await c.execute(sa.select(sa.func.count()).select_from(table))
