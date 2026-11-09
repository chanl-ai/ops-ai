"""The database holds documents-service's tables to the caller's tenant and team (migration documents_0011),
with raw SQL and no WHERE clause as ops_documents_tenant, by failure mode: a team transaction reading or writing
another team's document type, version, sample, test, example, extraction or correction; a transaction reading or
changing another tenant's readings or outbox events; a dropped policy that nobody notices; and the system role reaching
more than the outbox and the work a restart picks up. On the PostgreSQL test database migrated to head."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_documents.store import ReadingsStore, metadata
from ops_documents.store.extractions import extractions
from ops_documents.store.metadata import ROLE, SYSTEM_ROLE
from ops_documents.store.readings import documents_reading_files, documents_reading_pages, documents_readings
from ops_store import isolation
from ops_store.conformance import isolation_suite
from ops_store.schema import isolation_ddl, isolation_kind

TABLES = [t for t in metadata.sorted_tables if isolation_kind(t) in ("team", "tenant")]
# What the system role reads: the outbox (the relay) and the queued work a restart picks up again.
SYSTEM_READS = {"documents_outbox", "extractions", "document_type_tests", "documents_readings"}


def test_every_documents_table_is_marked() -> None:
    assert {t.name for t in metadata.sorted_tables} == {t.name for t in TABLES}


async def test_each_table_holds_a_team_or_a_tenant_to_its_rows(engine: AsyncEngine) -> None:
    assert await isolation_suite(engine, TABLES, role=ROLE) == []


async def test_a_dropped_policy_fails_the_suite_naming_its_table(engine: AsyncEngine) -> None:
    async with engine.begin() as c:
        await c.execute(sa.text("DROP POLICY extractions_isolation ON extractions"))
    try:
        failures = await isolation_suite(engine, TABLES, role=ROLE)
    finally:
        async with engine.begin() as c:
            for statement in isolation_ddl(extractions, "postgresql"):
                await c.execute(sa.text(statement))
    assert failures and {f.split(":")[0] for f in failures} == {"extractions"}, failures


async def test_the_system_role_reads_the_outbox_and_queued_work_and_nothing_else(engine: AsyncEngine) -> None:
    for table in TABLES:
        if table.name in SYSTEM_READS:
            async with engine.begin() as c:
                await c.execute(sa.text(f"SET LOCAL ROLE {SYSTEM_ROLE}"))
                await c.execute(sa.select(sa.func.count()).select_from(table))
            continue
        with pytest.raises(ProgrammingError, match="permission denied"):
            async with engine.begin() as c:
                await c.execute(sa.text(f"SET LOCAL ROLE {SYSTEM_ROLE}"))
                await c.execute(sa.select(sa.func.count()).select_from(table))


async def test_one_team_cannot_read_another_teams_reading_of_the_same_bytes(engine: AsyncEngine, tenant: str) -> None:
    store = ReadingsStore(engine)
    page = {"number": 1, "source": "text", "text": "Overdraft limits for the cards team"}
    with isolation.scope(tenant, "team_ops"):
        await store.link("f_ops", "team_ops", "d1", datetime.now(UTC))
        await store.put_done(
            "d1", "v1", "auto:eng", facts={}, pages=[page], file_id="f_ops", team="team_ops", actor="a",
            duration_ms=1, at=datetime.now(UTC),
        )  # fmt: skip
    with isolation.scope(tenant, "team_cards"):
        # Naming the other team's reading outright, as a caller that knows its digest would.
        seen = [await store.get(team, "d1", "v1", "auto:eng") for team in ("team_cards", "team_ops")]
        pages = [await store.pages(team, "d1", "v1", "auto:eng") for team in ("team_cards", "team_ops")]
        async with isolation.isolated_tx(engine, role=ROLE) as c:
            raw = {
                t.name: (await c.execute(sa.select(sa.func.count()).select_from(t))).scalar_one()
                for t in (documents_readings, documents_reading_pages, documents_reading_files)
            }
    assert seen == [None, None] and pages == [[], []], (seen, pages)
    assert raw == dict.fromkeys(raw, 0), raw
