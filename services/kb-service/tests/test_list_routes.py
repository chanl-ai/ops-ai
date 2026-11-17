"""The four lists on the shared list contract, each through its route, by failure mode: another tenant's or another
team's row shown; the total counting rows the caller cannot see; a page asked past the end answering empty instead
of the last page; rows that share a sort value repeated or skipped between pages."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_kb.store import KnowledgeStore
from ops_kb.store.document_list import document_page
from ops_kb.store.knowledge import NewBase, NewSource, kb_items, kb_runs
from ops_service_kit.listing import ListParams
from ops_store import isolation
from ops_store.team_scope import acting_as

from .test_provisioned_bases import kb, person  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture
from .test_team_isolation import outsider

# One moment for every seeded row, so only the primary key orders them.
AT = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)


def source_row(tenant: str, team: str, name: str) -> NewSource:
    return {
        "tenant_id": tenant,
        "id": f"src_{uuid4().hex[:12]}",
        "team_id": team,
        "type": "file",
        "name": name,
        "collection": "Policies",
        "owner": "Card operations",
        "sensitivity": "internal",
        "status": "active",
        "tags": [],
        "file_ids": [],
        "file_names": {},
        "created_by": "james@harborpine.example",
        "created_at": AT,
    }


async def _seed_sources(engine: AsyncEngine, tenant: str, team: str, *names: str) -> list[str]:
    store = KnowledgeStore(engine)
    made = [source_row(tenant, team, n) for n in names]
    with isolation.scope(tenant, team):
        for row in made:
            await store.create_source(row, [])
    return [r["id"] for r in made]


async def insert_rows(engine: AsyncEngine, tenant: str, team: str, table: sa.Table, *rows: dict[str, Any]) -> list[str]:
    """Rows written as `team` in `tenant`, with no check that their source is that team's: a stray row the list's own
    predicates must leave out."""
    with isolation.scope(tenant, team):
        async with KnowledgeStore(engine).tx() as c:
            for row in rows:
                await c.execute(sa.insert(table).values(tenant_id=tenant, team_id=team, **row))
    return [r["id"] for r in rows]


def run_row(source_id: str) -> dict[str, Any]:
    return {
        "id": f"run_{uuid4().hex[:12]}",
        "source_id": source_id,
        "trigger": "manual",
        "started_at": AT,
        "duration_sec": 1.0,
        "status": "success",
        "counts": {},
        "errors": [],
        "log": [],
        "started_by": "james@harborpine.example",
    }


def item_row(source_id: str, title: str, status: str = "indexed") -> dict[str, Any]:
    return {
        "id": f"item_{uuid4().hex[:12]}",
        "source_id": source_id,
        "path": f"{title}.pdf",
        "title": title,
        "mime": "application/pdf",
        "size": 10,
        "file_id": f"file_{uuid4().hex[:12]}",
        "digest": "d",
        "version": 1,
        "status": status,
        "chunk_count": 0,
        "owner": "Card operations",
        "created_at": AT,
    }


async def _page(c: httpx.AsyncClient, path: str, **params: Any) -> dict[str, Any]:
    r = await c.get(path, params=params)
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_sources_list_only_the_teams_rows_with_ties_ordered_by_id(
    kb: httpx.AsyncClient,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
) -> None:
    mine = await _seed_sources(engine, tenant, "team_ops", "Rates", "Hardship", "Mortgages")
    lending = await _seed_sources(engine, tenant, "team_lending", "Lending rates")
    elsewhere = f"t_{uuid4().hex[:10]}"
    other = await _seed_sources(engine, elsewhere, "team_ops", "Other tenant rates")

    first = await _page(kb, "/v1/sources", pageSize=2)
    second = await _page(kb, "/v1/sources", pageSize=2, page=2)
    past = await _page(kb, "/v1/sources", pageSize=2, page=9)
    shown = [r["id"] for r in first["data"] + second["data"]]
    # The same created_at for all three: the newest-first list then orders them by id, descending.
    assert shown == sorted(mine, reverse=True)
    assert (first["pagination"]["total"], first["facets"]["type"]) == (3, {"file": 3})
    assert (past["pagination"]["page"], [r["id"] for r in past["data"]]) == (2, [r["id"] for r in second["data"]])

    theirs = (await kb.get("/v1/sources", headers=outsider(tenant))).json()["data"]
    assert ([r["id"] for r in theirs["data"]], theirs["pagination"]["total"]) == (lending, 1)
    another = (await kb.get("/v1/sources", headers=person(elsewhere, "james@harborpine.example", "builder"))).json()
    assert [r["id"] for r in another["data"]["data"]] == other


async def _per_source_list(
    kb: httpx.AsyncClient,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
    *,
    child: str,
    table: sa.Table,
    make: Callable[[str, str], dict[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    """Three rows of one source at one moment, and rows on the same source id written as another team and in another
    tenant (where a source of that id is that tenant's own); the route must answer the three alone."""
    [sid] = await _seed_sources(engine, tenant, "team_ops", "Rates")
    elsewhere = f"t_{uuid4().hex[:10]}"
    other = source_row(elsewhere, "team_ops", "Rates")
    with isolation.scope(elsewhere, "team_ops"):
        await KnowledgeStore(engine).create_source({**other, "id": sid}, [])
    mine = await insert_rows(engine, tenant, "team_ops", table, make(sid, "a"), make(sid, "b"), make(sid, "c"))
    await insert_rows(engine, tenant, "team_lending", table, make(sid, "d"))
    await insert_rows(engine, elsewhere, "team_ops", table, make(sid, "e"))

    path = f"/v1/sources/{sid}/{child}"
    first = await _page(kb, path, pageSize=2)
    second = await _page(kb, path, pageSize=2, page=2)
    past = await _page(kb, path, pageSize=2, page=9)
    shown = [r["id"] for r in first["data"] + second["data"]]
    assert first["pagination"]["total"] == 3
    assert (past["pagination"]["page"], [r["id"] for r in past["data"]]) == (2, [r["id"] for r in second["data"]])
    return shown, {"mine": mine, "first": first}


async def test_runs_list_only_the_sources_team_rows_newest_first_with_ties_by_id(
    kb: httpx.AsyncClient,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
) -> None:
    def make(sid: str, _n: str) -> dict[str, Any]:
        return run_row(sid)

    shown, seen = await _per_source_list(kb, engine, tenant, child="runs", table=kb_runs, make=make)
    assert shown == sorted(seen["mine"], reverse=True)
    assert seen["first"]["facets"]["status"] == {"success": 3}


async def test_items_list_only_the_sources_team_rows_oldest_first_with_ties_by_id(
    kb: httpx.AsyncClient,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
) -> None:
    def make(sid: str, n: str) -> dict[str, Any]:
        return item_row(sid, f"Policy {n}", "reading" if n == "a" else "indexed")

    try:
        shown, seen = await _per_source_list(kb, engine, tenant, child="items", table=kb_items, make=make)
        assert shown == sorted(seen["mine"])
        # Stored as reading, shown and counted as processing.
        assert seen["first"]["facets"]["status"] == {"processing": 1, "indexed": 2}
    finally:
        # A reading item's file is in no store, and the schedule picks up every tenant's waiting items.
        with isolation.scope(tenant, "team_ops"):
            async with KnowledgeStore(engine).tx() as c:
                await c.execute(
                    sa.delete(kb_items).where(kb_items.c.tenant_id == tenant, kb_items.c.status == "reading")
                )


def base_row(tenant: str, team: str, name: str, *, refreshed: bool = True, template: str | None = None) -> NewBase:
    return {
        "tenant_id": tenant,
        "id": f"kb_{uuid4().hex[:12]}",
        "team_id": team,
        "name": name,
        "slug": name.lower().replace(" ", "_"),
        "description": f"{name} for the card desk",
        "color": "blue",
        "owner": "Card operations",
        "collections": [],
        "retrieval": {},
        "created_by": "james@harborpine.example",
        "created_at": AT,
        "last_refreshed_at": AT if refreshed else None,
        "template_id": template,
    }


async def test_bases_list_only_the_teams_rows_with_health_counted_and_ids_answered(
    kb: httpx.AsyncClient,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
) -> None:
    store = KnowledgeStore(engine)
    [failing] = await _seed_sources(engine, tenant, "team_ops", "Rates")
    await insert_rows(engine, tenant, "team_ops", kb_items, item_row(failing, "Rate sheet", "failed"))
    amber = base_row(tenant, "team_ops", "Hardship", refreshed=False)
    amber["color"] = "amber"
    made = [
        base_row(tenant, "team_ops", "Disputes", template="banking/policies"),
        amber,
        base_row(tenant, "team_ops", "Rates"),
    ]
    with isolation.scope(tenant, "team_ops"):
        for row in made:
            await store.create_base(row, [failing] if row["name"] == "Rates" else [])
    lending = base_row(tenant, "team_lending", "Lending")
    with isolation.scope(tenant, "team_lending"):
        await store.create_base(lending, [])
    elsewhere = f"t_{uuid4().hex[:10]}"
    other = base_row(elsewhere, "team_ops", "Other tenant rates")
    with isolation.scope(elsewhere, "team_ops"):
        await store.create_base(other, [])
    mine = sorted((r["id"] for r in made), reverse=True)

    first = await _page(kb, "/v1/knowledge-bases", pageSize=2)
    second = await _page(kb, "/v1/knowledge-bases", pageSize=2, page=2)
    past = await _page(kb, "/v1/knowledge-bases", pageSize=2, page=9)
    assert [r["id"] for r in first["data"] + second["data"]] == mine
    assert first["pagination"]["total"] == 3
    assert first["facets"]["health"] == {"healthy": 1, "never": 1, "degraded": 1}
    assert {r["name"]: r["health"] for r in first["data"] + second["data"]} == {
        "Disputes": "healthy",
        "Hardship": "never",
        "Rates": "degraded",
    }
    assert (past["pagination"]["page"], [r["id"] for r in past["data"]]) == (2, [r["id"] for r in second["data"]])

    # Pickers and the chat screens' labels: exact rows by id with each base's own name and colour, whatever the
    # search says, never another team's; search and the template filter.
    picked = await _page(kb, "/v1/knowledge-bases", ids=[made[1]["id"], lending["id"]], search="zzz")
    assert [(r["id"], r["name"], r["color"]) for r in picked["data"]] == [(made[1]["id"], "Hardship", "amber")]
    assert [r["name"] for r in (await _page(kb, "/v1/knowledge-bases", search="hards"))["data"]] == ["Hardship"]
    templated = await _page(kb, "/v1/knowledge-bases", templateId="banking/policies")
    assert [r["name"] for r in templated["data"]] == ["Disputes"]

    theirs = (await kb.get("/v1/knowledge-bases", headers=outsider(tenant))).json()["data"]
    assert ([r["id"] for r in theirs["data"]], theirs["pagination"]["total"]) == ([lending["id"]], 1)
    another = await kb.get("/v1/knowledge-bases", headers=person(elsewhere, "james@harborpine.example", "builder"))
    assert [r["id"] for r in another.json()["data"]["data"]] == [other["id"]]


# The store's own team predicate, with the row policy widened to every team of the tenant: only the query's
# `team_visible` keeps team_lending's rows out of a team_ops page, its total and its facets.
WIDE = "test: the list query's own team predicate, with the row policy open to every team"


async def test_base_page_keeps_another_teams_rows_out_by_its_own_predicate(engine: AsyncEngine, tenant: str) -> None:
    store = KnowledgeStore(engine)
    mine = [base_row(tenant, "team_ops", "Rates"), base_row(tenant, "team_ops", "Hardship", refreshed=False)]
    with isolation.scope(tenant, "team_ops"):
        for row in mine:
            await store.create_base(row, [])
    with isolation.scope(tenant, "team_lending"):
        await store.create_base(base_row(tenant, "team_lending", "Lending"), [])
    with isolation.tenant_wide(WIDE, tenant_id=tenant), acting_as("team_ops"):
        page = (await store.base_page(tenant, ListParams())).page
    assert [r["id"] for r in page["data"]] == sorted((r["id"] for r in mine), reverse=True)
    assert (page["pagination"]["total"], page["facets"]) == (2, {"health": {"healthy": 1, "never": 1}})


async def test_source_page_keeps_another_teams_rows_out_by_its_own_predicate(engine: AsyncEngine, tenant: str) -> None:
    mine = await _seed_sources(engine, tenant, "team_ops", "Rates", "Hardship")
    await _seed_sources(engine, tenant, "team_lending", "Lending rates")
    with isolation.tenant_wide(WIDE, tenant_id=tenant), acting_as("team_ops"):
        page = (await KnowledgeStore(engine).source_page(tenant, ListParams())).page
    assert [r["id"] for r in page["data"]] == sorted(mine, reverse=True)
    assert (page["pagination"]["total"], page["facets"]) == (2, {"type": {"file": 2}, "status": {"active": 2}})


async def test_run_page_keeps_another_teams_rows_out_by_its_own_predicate(engine: AsyncEngine, tenant: str) -> None:
    [sid] = await _seed_sources(engine, tenant, "team_ops", "Rates")
    mine = await insert_rows(engine, tenant, "team_ops", kb_runs, run_row(sid), run_row(sid))
    await insert_rows(engine, tenant, "team_lending", kb_runs, {**run_row(sid), "status": "failed"})
    with isolation.tenant_wide(WIDE, tenant_id=tenant), acting_as("team_ops"):
        page, _ = await KnowledgeStore(engine).run_page(tenant, sid, ListParams())
    assert [r["id"] for r in page["data"]] == sorted(mine, reverse=True)
    assert (page["pagination"]["total"], page["facets"]) == (2, {"status": {"success": 2}})


async def test_item_page_keeps_another_teams_rows_out_by_its_own_predicate(engine: AsyncEngine, tenant: str) -> None:
    [sid] = await _seed_sources(engine, tenant, "team_ops", "Rates")
    mine = await insert_rows(engine, tenant, "team_ops", kb_items, item_row(sid, "Rate sheet"), item_row(sid, "Fees"))
    await insert_rows(engine, tenant, "team_lending", kb_items, item_row(sid, "Lending sheet", "failed"))
    with isolation.tenant_wide(WIDE, tenant_id=tenant), acting_as("team_ops"):
        page, _ = await KnowledgeStore(engine).item_page(tenant, sid, ListParams())
    assert [r["id"] for r in page["data"]] == sorted(mine)
    assert (page["pagination"]["total"], page["facets"]) == (2, {"status": {"indexed": 2}})


async def test_document_page_keeps_another_teams_rows_out_by_its_own_predicate(
    engine: AsyncEngine, tenant: str
) -> None:
    store = KnowledgeStore(engine)
    [sid] = await _seed_sources(engine, tenant, "team_ops", "Rates")
    base = base_row(tenant, "team_ops", "Rates")
    with isolation.scope(tenant, "team_ops"):
        await store.create_base(base, [sid])
    mine = await insert_rows(engine, tenant, "team_ops", kb_items, item_row(sid, "Rate sheet"), item_row(sid, "Fees"))
    await insert_rows(engine, tenant, "team_lending", kb_items, item_row(sid, "Lending sheet", "failed"))
    with isolation.tenant_wide(WIDE, tenant_id=tenant), acting_as("team_ops"):
        page, _ = await document_page(
            store, tenant, base["id"], ListParams(), freshness={sid: "fresh"}, tags={sid: ["rates"]}
        )
    assert [r["id"] for r in page["data"]] == sorted(mine)
    assert page["pagination"]["total"] == 2
    assert (page["facets"]["status"], page["facets"]["tags"]) == ({"indexed": 2}, {"rates": 2})


async def test_documents_list_only_the_bases_team_rows_with_tags_and_shown_status_faceted(
    kb: httpx.AsyncClient,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
) -> None:
    """A base's documents across two sources, with a row on the same source written as another team and in another
    tenant. Tags are the source's, several to a row: a row counts under each of its tags and once in the total."""
    store = KnowledgeStore(engine)
    cards = source_row(tenant, "team_ops", "Cards feed")
    cards["tags"] = ["cards", "disputes"]
    rules = source_row(tenant, "team_ops", "Rules feed")
    rules["tags"] = ["cards"]
    cards["collection"], rules["collection"] = "Cards", "Compliance"
    with isolation.scope(tenant, "team_ops"):
        for row in (cards, rules):
            await store.create_source(row, [])
    base = base_row(tenant, "team_ops", "Card policies")
    with isolation.scope(tenant, "team_ops"):
        await store.create_base(base, [cards["id"], rules["id"]])
    elsewhere = f"t_{uuid4().hex[:10]}"
    with isolation.scope(elsewhere, "team_ops"):
        await store.create_source({**source_row(elsewhere, "team_ops", "Cards feed"), "id": cards["id"]}, [])
    mine = await insert_rows(
        engine,
        tenant,
        "team_ops",
        kb_items,
        item_row(cards["id"], "Dispute limits"),
        item_row(cards["id"], "Chargebacks", "reading"),
        item_row(cards["id"], "Lost card"),
        item_row(rules["id"], "Complaints policy"),
    )
    await insert_rows(engine, tenant, "team_lending", kb_items, item_row(cards["id"], "Lending sheet", "failed"))
    await insert_rows(engine, elsewhere, "team_ops", kb_items, item_row(cards["id"], "Other tenant sheet", "failed"))
    path = f"/v1/knowledge-bases/{base['id']}/documents"
    try:
        first = await _page(kb, path, pageSize=2)
        second = await _page(kb, path, pageSize=2, page=2)
        past = await _page(kb, path, pageSize=2, page=9)
        assert [r["id"] for r in first["data"] + second["data"]] == sorted(mine)
        assert first["pagination"]["total"] == 4
        assert (past["pagination"]["page"], [r["id"] for r in past["data"]]) == (2, [r["id"] for r in second["data"]])
        assert first["facets"] == {
            "sourceId": {cards["id"]: 3, rules["id"]: 1},
            "status": {"indexed": 3, "processing": 1},
            "collection": {"Cards": 3, "Compliance": 1},
            "docType": {"pdf": 4},
            "freshness": {"no_schedule": 4},
            "sensitivity": {"internal": 4},
            "tags": {"cards": 4, "disputes": 3},
        }
        # A tag keeps the rows holding it; its own facet still counts every tag over the other filters.
        tagged = await _page(kb, path, tags="disputes", status="indexed")
        indexed = [mine[0], mine[2]]
        assert ([r["id"] for r in tagged["data"]], tagged["pagination"]["total"]) == (sorted(indexed), 2)
        assert tagged["facets"]["tags"] == {"cards": 3, "disputes": 2}
        assert tagged["facets"]["status"] == {"indexed": 2, "processing": 1}
        shown = await _page(kb, path, status="processing", search="charge")
        assert [r["title"] for r in shown["data"]] == ["Chargebacks"]
        assert (await _page(kb, path, tags="disputes", collection="Compliance"))["pagination"]["total"] == 0
    finally:
        with isolation.scope(tenant, "team_ops"):
            async with store.tx() as c:
                await c.execute(
                    sa.delete(kb_items).where(kb_items.c.tenant_id == tenant, kb_items.c.status == "reading")
                )


async def test_a_duplicate_names_its_copy_only_when_the_callers_team_can_see_it(
    kb: httpx.AsyncClient,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
) -> None:
    """The copy a duplicate repeats is named on the list row and the detail when it is the caller's team's; another
    team's copy keeps its id but gives no title or source name."""
    [mine] = await _seed_sources(engine, tenant, "team_ops", "Rates")
    [lending] = await _seed_sources(engine, tenant, "team_lending", "Lending rates")
    [kept] = await insert_rows(engine, tenant, "team_ops", kb_items, item_row(mine, "Rate sheet"))
    [hidden] = await insert_rows(engine, tenant, "team_lending", kb_items, item_row(lending, "Lending sheet"))
    same, other = item_row(mine, "Rate sheet copy"), item_row(mine, "Lending copy")
    await insert_rows(
        engine, tenant, "team_ops", kb_items, {**same, "duplicate_of": kept}, {**other, "duplicate_of": hidden}
    )
    rows = {r["id"]: r for r in (await _page(kb, f"/v1/sources/{mine}/items"))["data"]}
    assert rows[same["id"]]["duplicateCopy"] == {"title": "Rate sheet", "sourceName": "Rates"}
    assert rows[other["id"]]["duplicateOf"] == hidden and "duplicateCopy" not in rows[other["id"]]
    detail = await _page(kb, f"/v1/items/{other['id']}")
    assert detail["duplicateOf"] == hidden and "duplicateCopy" not in detail, detail
    # The query's own predicates, with the row policy open to every team: another team's item in this team's source
    # and this team's item in another team's source are not named.
    [crossed] = await insert_rows(engine, tenant, "team_lending", kb_items, item_row(mine, "Crossed sheet"))
    [stray] = await insert_rows(engine, tenant, "team_ops", kb_items, item_row(lending, "Stray sheet"))
    with isolation.tenant_wide(WIDE, tenant_id=tenant), acting_as("team_ops"):
        named = await KnowledgeStore(engine).copy_names(tenant, [kept, hidden, crossed, stray])
    assert [c.id for c in named] == [kept]
