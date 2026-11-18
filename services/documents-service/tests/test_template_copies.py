"""Where a team's document type copies came from (migration documents_0014), by failure mode: a team reads or
writes another team's copies, so it could find another team's type as its own copy; a second install of the same
template version makes a second live copy; and a copy whose type was deleted still counts, so the template can never be
installed again. On the PostgreSQL test database migrated to head, as ops_documents_tenant."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_documents.store.metadata import ROLE
from ops_documents.store.template_copies import CopyRow, TemplateCopies, template_copies
from ops_store import isolation
from ops_store.conformance import isolation_suite

SOURCE = "plugin:test.templates"
# The rig connects to SQL Server as the administrator, so the service's runtime user is impersonated there.
RUNTIME = "ops_documents_runtime"


async def test_the_table_holds_a_team_to_its_rows(engine: AsyncEngine) -> None:
    assert await isolation_suite(engine, (template_copies,), role=ROLE) == []


async def test_one_live_copy_per_version_and_a_removed_one_lets_a_new_copy_in(engine: AsyncEngine, tenant: str) -> None:
    store = TemplateCopies(engine)

    async def add(record_id: str, version: int = 1) -> tuple[CopyRow, bool]:
        return await store.add(
            team="team_ops",
            kind="document_type",
            record_id=record_id,
            source=SOURCE,
            template_id="case-letter",
            version=version,
            by="j@x",
        )

    with isolation.scope(tenant, "team_ops"):
        first, made = await add("dt_1")
        again, made_again = await add("dt_2")
        assert made and not made_again and again.id == first.id and again.record_id == "dt_1"
        await store.removed(first.id)
        assert await store.live(SOURCE, "case-letter") is None
        fresh, made_fresh = await add("dt_3")
        assert made_fresh and fresh.record_id == "dt_3"
        # Another version of the same template finds the copy the team holds: one copy follows one template.
        held, made_v2 = await add("dt_4", version=2)
        assert not made_v2 and held.record_id == "dt_3"
        # A detached copy stops counting, so a fresh one can be made, and keeps its row for the type's page.
        await store.detach(fresh.id, by="j@x")
        _, made_after = await add("dt_5", version=2)
        assert made_after
        assert sorted(c.record_id for c in await store.of_team()) == ["dt_5"]
        assert getattr(await store.of_record("dt_3"), "detached_by", None) == "j@x"
    with isolation.scope(tenant, "team_platform"):
        assert await store.live(SOURCE, "case-letter") is None and await store.of_team() == []


async def test_a_tenants_transaction_cannot_delete_a_copy(engine: AsyncEngine, tenant: str) -> None:
    """A removed copy keeps its row, marked deleted, so a reinstall finds where it came from: as ops_documents_tenant
    on PostgreSQL and the runtime user on SQL Server, a DELETE is refused."""
    with isolation.scope(tenant, "team_ops"):
        async with isolation.isolated_tx(engine, role=ROLE) as c:
            mssql = c.dialect.name == "mssql"
            if mssql:
                await c.execute(sa.text(f"EXECUTE AS USER = N'{RUNTIME}'"))
            with pytest.raises(DBAPIError) as e:
                async with isolation.attempt(c):
                    await c.execute(template_copies.delete().where(template_copies.c.tenant_id == tenant))
            if mssql:
                await c.execute(sa.text("REVERT"))
    assert "permission" in str(e.value).lower() and "denied" in str(e.value).lower()
