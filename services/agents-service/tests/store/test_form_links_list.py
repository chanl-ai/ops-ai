"""A workflow's forms a page at a time in SQL (`FormLinks.page`), by failure mode: another team's form of the same
workflow on the page when the database lets every team through; two forms made in one moment repeated or lost between
pages."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.form_links import FormLinks, form_links
from ops_agents.store.tenancy import tenant_tx
from ops_service_kit.listing import ListParams
from ops_store import isolation
from ops_store.team_scope import acting_as

TEAM, OTHER = "team_cards", "team_lending"
FLOW = "payment_plan"


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


@pytest.fixture
def tenant() -> str:
    return f"t_{uuid4().hex[:10]}"


async def _form(e: AsyncEngine, team: str, slug: str) -> str:
    row = await FormLinks(e).create(
        team_id=team,
        workflow_id=FLOW,
        slug=slug,
        mode="link",
        daily_cap=10,
        expires_at="2030-01-01T00:00:00+00:00",
        created_by="p@x.example",
        title=slug,
    )
    return str(row["id"])


async def _ids(e: AsyncEngine, **params: Any) -> list[str]:
    return [str(r["id"]) for r in (await FormLinks(e).page(FLOW, ListParams(**params)))["data"]]


async def test_the_page_holds_the_acting_team_when_the_policy_lets_every_team_through(
    engine: AsyncEngine, tenant: str
) -> None:
    with isolation.scope(tenant, TEAM):
        mine = await _form(engine, TEAM, f"card-{tenant}")
    with isolation.scope(tenant, OTHER):
        theirs = await _form(engine, OTHER, f"loan-{tenant}")
    # Tenant-wide with a team acting, so the database policy lets every team through and the query alone holds them.
    with (
        isolation.tenant_wide("a test reads a workflow's forms with every team let through", tenant_id=tenant),
        acting_as(TEAM),
    ):
        seen = await _ids(engine)
        named = await _ids(engine, ids=[mine, theirs])
    assert (seen, named) == ([mine], [mine])


async def test_forms_made_in_one_moment_page_by_id(engine: AsyncEngine, tenant: str) -> None:
    with isolation.scope(tenant, TEAM):
        made = sorted([await _form(engine, TEAM, f"same-{i}-{tenant}") for i in range(3)], reverse=True)
        async with tenant_tx(engine) as c:
            await c.execute(sa.update(form_links).where(form_links.c.id.in_(made)).values(created_at="2026-01-01"))
        seen = [i for p in (1, 2, 3) for i in await _ids(engine, page=p, page_size=1)]
    # Newest first, then by id in the same direction.
    assert seen == made
