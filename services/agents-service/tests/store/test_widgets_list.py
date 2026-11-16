"""The widgets list's registry page in one statement (`WidgetRegistry.page`), by failure mode: another team's widget
on the page when the database lets every team through; a widget shown with an older version's content or the wrong
status (a waiting publish request not seen, another widget's request counted); `ids` reaching a widget outside the
caller's teams."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.agent_registry import AgentRegistry
from ops_agents.store.widgets import WidgetRegistry
from ops_store import isolation
from ops_store.team_scope import acting_as

TEAM, OTHER = "team_cards", "team_lending"


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


@pytest.fixture
def tenant() -> str:
    return f"t_{uuid4().hex[:10]}"


def _content(name: str) -> dict[str, Any]:
    return {"name": name, "useWhen": "always", "tree": {}, "dataSchema": {"type": "object"}, "sample": {}}


async def test_the_page_holds_the_acting_team_when_the_policy_lets_every_team_through(
    engine: AsyncEngine, tenant: str
) -> None:
    reg = WidgetRegistry(engine)
    with isolation.scope(tenant, TEAM):
        await reg.create("card-limit", _content("Card limit"), team_id=TEAM, by="u")
    with isolation.scope(tenant, OTHER):
        await reg.create("loan-limit", _content("Loan limit"), team_id=OTHER, by="u")
    both = [TEAM, OTHER]
    # Tenant-wide with a team acting, so the database policy lets every team through and the query alone holds them.
    with isolation.tenant_wide("a test reads the widgets list with every team let through", tenant_id=tenant):
        with acting_as(TEAM):
            mine = [r.id for r in await reg.page(both, "", 0, 10)]
            counted = await reg.count(both, "")
        with acting_as(OTHER):
            theirs = [r.id for r in await reg.page(both, "", 0, 10, ["card-limit", "loan-limit"])]
    assert (mine, counted, theirs) == (["card-limit"], 1, ["loan-limit"])


async def test_each_row_carries_its_newest_content_and_only_its_own_waiting_request(
    engine: AsyncEngine, tenant: str
) -> None:
    reg = WidgetRegistry(engine)
    with isolation.scope(tenant, TEAM):
        await reg.create("limit", _content("Limit"), team_id=TEAM, by="u")
        await reg.publish("limit", 1, by="r", review_id="rv_1")
        await reg.save_draft("limit", _content("Limit two"), by="u")
        await reg.create("quiet", _content("Quiet"), team_id=TEAM, by="u")
        await AgentRegistry(engine).open_request("widget", "limit", 2, note="", by="u", body={}, approved=False)
        rows = await reg.page([TEAM], "", 0, 10)
        named = await reg.page([TEAM], "", 0, 10, ["quiet", "elsewhere"])
    got = [(r.id, r.version, r.content["name"], r.pending, r.published_at) for r in rows]
    assert got == [("limit", 2, "Limit two", True, None), ("quiet", 1, "Quiet", False, None)]
    assert [r.id for r in named] == ["quiet"]
