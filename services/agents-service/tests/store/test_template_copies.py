"""Where a team's copies came from (c-590), by failure mode: a team reads or writes another team's copies, so it could
find another team's agent as its own copy; a second install of the same template version makes a second live copy;
and a copy whose record was deleted still counts, so the template can never be installed again. On the PostgreSQL
test database migrated to head, as ops_runtime_tenant."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.template_copies import TemplateCopies, template_copies
from ops_agents.store.tenancy import TENANT_ROLE, tenant_scope
from ops_store import isolation
from ops_store.conformance import isolation_suite

SOURCE = "plugin:test.templates"


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def test_the_table_holds_a_team_to_its_rows(engine: AsyncEngine) -> None:
    assert await isolation_suite(engine, (template_copies,), role=TENANT_ROLE) == []


async def test_one_live_copy_per_version_and_a_removed_one_lets_a_new_copy_in(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    store = TemplateCopies(engine)
    with tenant_scope(tenant), isolation.scope(tenant, "team_ops"):
        first, made = await store.add(
            team_id="team_ops",
            kind="agent",
            record_id="ag_1",
            source=SOURCE,
            template_id="case-helper",
            version=2,
            by="a",
        )
        again, made_again = await store.add(
            team_id="team_ops",
            kind="agent",
            record_id="ag_2",
            source=SOURCE,
            template_id="case-helper",
            version=2,
            by="b",
        )
        assert made and not made_again and again["id"] == first["id"] and again["record_id"] == "ag_1"
        await store.removed(first["id"])
        assert await store.live(SOURCE, "case-helper", 2) is None
        fresh, made_fresh = await store.add(
            team_id="team_ops",
            kind="agent",
            record_id="ag_3",
            source=SOURCE,
            template_id="case-helper",
            version=2,
            by="c",
        )
        assert made_fresh and fresh["record_id"] == "ag_3"
        # Another version is another template version: it has a live copy of its own.
        _, made_v3 = await store.add(
            team_id="team_ops",
            kind="agent",
            record_id="ag_4",
            source=SOURCE,
            template_id="case-helper",
            version=3,
            by="d",
        )
        assert made_v3
    with tenant_scope(tenant), isolation.scope(tenant, "team_platform"):
        assert await store.live(SOURCE, "case-helper", 2) is None and await store.of_team() == []
