"""The v2 workflows list a page at a time in SQL (`definitions_page`), by failure mode: another team's workflow on the
page or in the counts when the database lets every team through; a status worked out wrong in SQL (in review from a
pending request, archived over every stage); an archived workflow shown by default or missing from its count;
workflows of one update time repeated or lost between pages."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.agent_registry import publish_requests
from ops_agents.store.definition_list import definitions_page
from ops_agents.store.tenancy import tenant_tx
from ops_engine.store.tables import engine_definitions
from ops_service_kit.listing import ListParams
from ops_store import isolation
from ops_store.team_scope import acting_as

AT = "2026-11-16T09:00:00.000Z"
TEAM, OTHER = "team_cards", "team_lending"


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


@pytest.fixture
def tenant() -> str:
    return f"t_{uuid4().hex[:10]}"


async def _version(
    e: AsyncEngine, wf: str, version: int, *, team: str | None = TEAM, stage: str = "draft", archived: bool = False
) -> None:
    async with tenant_tx(e) as c:
        await c.execute(
            engine_definitions.insert().values(
                tenant_id=isolation.tenant(),
                workflow_id=wf,
                version=version,
                digest=f"{wf}_{version}",
                name=wf.title(),
                definition={},
                created_at=AT,
                created_by="a@x.example",
                team_id=team,
                stage=stage,
                archived_at=AT if archived else None,
            )
        )


async def _pending(e: AsyncEngine, wf: str) -> None:
    async with tenant_tx(e) as c:
        await c.execute(
            publish_requests.insert().values(
                id=f"WFP-{wf}",
                kind="engine",
                subject_id=wf,
                version=1,
                status="pending",
                note="",
                requested_by="a@x.example",
                created_at=AT,
                body={},
            )
        )


async def _listed(e: AsyncEngine, **params: Any) -> tuple[list[tuple[str, str]], int, dict[str, int]]:
    page = await definitions_page(e, ListParams(**params))
    rows = [(str(r["workflow_id"]), str(r["status"])) for r in page["data"]]
    return rows, page["pagination"]["total"], page["facets"]["status"]


async def test_the_page_and_counts_hold_the_acting_team_when_the_policy_lets_every_team_through(
    engine: AsyncEngine, tenant: str
) -> None:
    with isolation.scope(tenant, TEAM):
        await _version(engine, "wf_mine", 1)
        await _version(engine, "wf_shared", 1, team=None)
    with isolation.scope(tenant, OTHER):
        await _version(engine, "wf_theirs", 1, team=OTHER, stage="live")
    # Tenant-wide with a team acting, so the database policy lets every team through and the query alone holds them.
    with (
        isolation.tenant_wide("a test reads the workflows list with every team let through", tenant_id=tenant),
        acting_as(TEAM),
    ):
        listed = await _listed(engine, sort_by="name", sort_order="asc")
    assert listed == ([("wf_mine", "draft"), ("wf_shared", "draft")], 2, {"draft": 2})


async def test_status_is_worked_out_in_sql_and_archived_is_counted_but_shown_only_when_asked(
    engine: AsyncEngine, tenant: str
) -> None:
    with isolation.scope(tenant, TEAM):
        await _version(engine, "wf_draft", 1)
        await _version(engine, "wf_review", 1)
        await _pending(engine, "wf_review")
        await _version(engine, "wf_paused", 1, stage="paused")
        # The latest version is a draft; the serving version's stage is the workflow's.
        await _version(engine, "wf_paused", 2)
        await _version(engine, "wf_gone", 1, stage="live", archived=True)
        shown = await _listed(engine, sort_by="name", sort_order="asc")
        archived = await _listed(engine, filters={"status": ["archived"]})
    counts = {"draft": 1, "in_review": 1, "paused": 1, "archived": 1}
    assert shown == ([("wf_draft", "draft"), ("wf_paused", "paused"), ("wf_review", "in_review")], 3, counts)
    assert archived == ([("wf_gone", "archived")], 1, counts)


async def test_equal_update_times_page_by_the_key_without_repeats(engine: AsyncEngine, tenant: str) -> None:
    with isolation.scope(tenant, TEAM):
        for wf in ("wf_c", "wf_a", "wf_b"):
            await _version(engine, wf, 1)
        seen = [w for p in (1, 2, 3) for w, _ in (await _listed(engine, page=p, page_size=1))[0]]
    assert seen == ["wf_c", "wf_b", "wf_a"]
