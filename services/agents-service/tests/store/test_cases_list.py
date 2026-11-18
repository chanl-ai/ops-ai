"""The cases list a page at a time in SQL (`CaseStore.page`), by failure mode: another team's case on the page when
the database lets every team through; cases with one deadline repeated or lost between pages; a filter or the
word-by-word search keeping the wrong cases."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.cases import CaseStore, cases
from ops_agents.store.tenancy import tenant_tx
from ops_service_kit.listing import ListParams
from ops_store import isolation
from ops_store.team_scope import acting_as

AT, DUE = "2026-11-16T09:00:00.000Z", "2026-11-20T09:00:00.000Z"
TEAM, OTHER = "team_cards", "team_lending"


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


@pytest.fixture
def tenant() -> str:
    return f"t_{uuid4().hex[:10]}"


async def _case(e: AsyncEngine, case_id: str, subject: str, *, team: str = TEAM, priority: str = "low") -> None:
    async with tenant_tx(e) as c:
        await c.execute(
            cases.insert().values(
                id=case_id,
                team_id=team,
                subject=subject,
                status="open",
                priority=priority,
                response_due_at=DUE,
                resolution_due_at=DUE,
                created_by="t",
                created_at=AT,
                updated_at=AT,
            )
        )


async def _ids(e: AsyncEngine, teams: list[str], **params: Any) -> list[str]:
    return [r.id for r in (await CaseStore(e).page(teams, ListParams(**params)))[1]]


async def test_the_page_holds_the_acting_team_when_the_policy_lets_every_team_through(
    engine: AsyncEngine, tenant: str
) -> None:
    with isolation.scope(tenant, TEAM):
        await _case(engine, f"{tenant}_mine", "Card dispute")
    with isolation.scope(tenant, OTHER):
        await _case(engine, f"{tenant}_theirs", "Loan dispute", team=OTHER)
    both = [TEAM, OTHER]
    # Tenant-wide with a team acting, so the database policy lets every team through and the query alone holds them.
    with isolation.tenant_wide("a test reads the cases list with every team let through", tenant_id=tenant):
        with acting_as(TEAM):
            mine = await _ids(engine, both)
        with acting_as(OTHER):
            theirs = await _ids(engine, both)
    assert (mine, theirs) == ([f"{tenant}_mine"], [f"{tenant}_theirs"])


async def test_equal_deadlines_page_by_id_and_filters_and_words_narrow_the_page(
    engine: AsyncEngine, tenant: str
) -> None:
    with isolation.scope(tenant, TEAM):
        for n, subject, priority in (
            (3, "Loan application waiting on documents", "high"),
            (1, "Card", "low"),
            (2, "Wire", "high"),
        ):
            await _case(engine, f"{tenant}_{n}", subject, priority=priority)
        seen = [i for p in (1, 2, 3) for i in await _ids(engine, [TEAM], page=p, page_size=1)]
        high = await _ids(engine, [TEAM], filters={"priority": ["high"]})
        words = await _ids(engine, [TEAM], search="documents application")
    assert seen == [f"{tenant}_1", f"{tenant}_2", f"{tenant}_3"]
    assert (high, words) == ([f"{tenant}_2", f"{tenant}_3"], [f"{tenant}_3"])
