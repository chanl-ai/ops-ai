"""The task and case type lists a page at a time in SQL (`VersionedRecords.page`, shared by both), by failure mode:
another team's type on the page when the database lets every team through; a team's own type sorted before the seeded
ones, or two types with one name repeated or lost between pages; `ids` naming another team's type."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents import task_types as tt
from ops_agents.store.task_types import TaskTypeStore
from ops_service_kit.listing import ListParams
from ops_store import isolation
from ops_store.team_scope import acting_as

TEAM, OTHER = "team_cards", "team_lending"
SEED: dict[str, Any] = next(t for t in json.loads(tt.SEED_FILE.read_text()) if t["id"] == "write_approval")


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


@pytest.fixture
def tenant() -> str:
    return f"t_{uuid4().hex[:10]}"


async def _type(e: AsyncEngine, team: str, type_id: str, name: str) -> None:
    content = {**SEED, "id": type_id, "name": name}
    await TaskTypeStore(e, team).create(type_id, content, team_id=team, by="p@x", copied_from=None)


async def _ids(e: AsyncEngine, **params: Any) -> list[str]:
    return [r.id for r in (await TaskTypeStore(e).page(ListParams(**params)))[1]]


async def test_the_page_holds_the_acting_team_when_the_policy_lets_every_team_through(
    engine: AsyncEngine, tenant: str
) -> None:
    with isolation.scope(tenant, TEAM):
        await _type(engine, TEAM, "card_check", "Card check")
    with isolation.scope(tenant, OTHER):
        await _type(engine, OTHER, "loan_check", "Loan check")
    # Tenant-wide with a team acting, so the database policy lets every team through and the query alone holds them.
    with isolation.tenant_wide("a test reads the task types list with every team let through", tenant_id=tenant):
        with acting_as(TEAM):
            mine = await _ids(engine)
            named = await _ids(engine, ids=["card_check", "loan_check"])
        with acting_as(OTHER):
            theirs = await _ids(engine)
    assert (mine, named, theirs) == (["card_check"], ["card_check"], ["loan_check"])


async def test_equal_names_page_by_id(engine: AsyncEngine, tenant: str) -> None:
    with isolation.scope(tenant, TEAM):
        for type_id in ("check_c", "check_a", "check_b"):
            await _type(engine, TEAM, type_id, "Check")
        seen = [i for p in (1, 2, 3) for i in await _ids(engine, page=p, page_size=1)]
    assert seen == ["check_a", "check_b", "check_c"]
