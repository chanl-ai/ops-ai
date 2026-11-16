"""`list_page` on each database, by failure mode: a page counted or cut in Python, a page past the end answering
nothing, a facet that loses its other choices once one is picked, statements that grow with the rows, a search
narrowing the rows a picker asked for by id, and a filter column nobody declared."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.http import LabelledListResult
from ops_service_kit.listing import ListParams
from ops_service_kit.settings import Settings
from ops_store.backends import backends
from ops_store.conformance import engine_for, sql_server_database
from ops_store.database import open_database
from ops_store.listing import LISTED, list_page

SQL_SERVER = (os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD"))
meta = sa.MetaData()
agents = sa.Table(
    "store_test_list_agents",
    meta,
    sa.Column("id", sa.String(32), primary_key=True),
    sa.Column("name", sa.String(64), nullable=False),
)
runs = sa.Table(
    "store_test_list_runs",
    meta,
    sa.Column("id", sa.String(32), primary_key=True),
    sa.Column("title", sa.String(64), nullable=False),
    sa.Column("status", sa.String(16), nullable=False, info=LISTED),
    sa.Column("agent_id", sa.String(32), nullable=False, info=LISTED),
    sa.Column("minutes", sa.Integer, nullable=False, info=LISTED),
    sa.Column("note", sa.String(16), nullable=True),
    sa.Index("ix_store_test_list_runs_status", "status"),
)
LIST = sa.select(runs.c.id, runs.c.title, runs.c.status, agents.c.name.label("agent")).join(
    agents, agents.c.id == runs.c.agent_id
)
SHAPE: dict[str, Any] = {
    "search": [runs.c.title],
    "sortable": {"minutes": runs.c.minutes},
    "default_sort": runs.c.id,
    "filters": {"status": runs.c.status, "agent": runs.c.agent_id},
    "facets": {"status": runs.c.status, "agent": runs.c.agent_id, "desk": agents.c.name},
    "labels": {"agent": sa.select(agents.c.id, agents.c.name)},
}


def rows(n: int) -> list[dict[str, Any]]:
    """Run r01..: every third is held, the rest open; odd ones are Claims intake's; one in four is titled a refund."""
    return [
        {
            "id": f"r{i:02d}",
            "title": f"{'Refund' if i % 4 == 0 else 'Renewal'} {i:02d}",
            "status": "held" if i % 3 == 0 else "open",
            "agent_id": "a_claims" if i % 2 else "a_loans",
            "minutes": 100 - i,
        }
        for i in range(1, n + 1)
    ]


@pytest.fixture(params=["postgresql", "mssql"])
async def engine(request: pytest.FixtureRequest) -> AsyncIterator[AsyncEngine]:
    with sql_server_database("ops_list", *SQL_SERVER) as mssql:
        if request.param == "mssql":
            if mssql is None:
                pytest.skip("set OPS_MSSQL_SERVER and MSSQL_SA_PASSWORD to run on SQL Server")
            url = mssql
        else:
            (backend,) = backends(Settings().database_url)
            await (await engine_for(backend)).dispose()
            url = backend.url
        e = open_database(url)
        async with e.begin() as c:
            await c.run_sync(meta.drop_all)
            await c.run_sync(meta.create_all)
            await c.execute(
                agents.insert(), [{"id": "a_claims", "name": "Claims intake"}, {"id": "a_loans", "name": "Loan desk"}]
            )
        yield e
        async with e.begin() as c:
            await c.run_sync(meta.drop_all)
        await e.dispose()


async def seed(engine: AsyncEngine, n: int) -> None:
    async with engine.begin() as c:
        await c.execute(runs.delete())
        await c.execute(runs.insert(), rows(n))


async def test_a_page_is_filtered_sorted_counted_and_cut_in_sql_and_one_past_the_end_answers_the_last(
    engine: AsyncEngine,
) -> None:
    await seed(engine, 12)
    asked = ListParams(
        page=9,
        page_size=3,
        search="renewal",
        sort_by="minutes",
        sort_order="asc",
        filters={"status": ["open"], "x": ["1"]},
    )
    async with engine.connect() as c:
        page = await list_page(c, LIST, asked, **SHAPE)
    # Open renewals are r01 r02 r05 r07 r10 r11; fewest minutes first is the highest number first.
    assert [r["id"] for r in page["data"]] == ["r05", "r02", "r01"]
    assert page["data"][0] == {"id": "r05", "title": "Renewal 05", "status": "open", "agent": "Claims intake"}
    assert page["pagination"] == {
        "page": 2,
        "pageSize": 3,
        "total": 6,
        "totalPages": 2,
        "hasNext": False,
        "hasPrev": True,
    }


async def test_a_facet_keeps_its_other_choices_while_one_is_picked_and_names_each_value(engine: AsyncEngine) -> None:
    await seed(engine, 12)
    async with engine.connect() as c:
        page = await list_page(c, LIST, ListParams(page_size=5, filters={"status": ["held"]}), **SHAPE)
    assert page["pagination"]["total"] == 4
    # Its own filter left out: picking held still shows how many are open. The other facet counts the held rows.
    assert page["facets"] == {
        "status": {"held": 4, "open": 8},
        "agent": {"a_claims": 2, "a_loans": 2},
        # A facet on the joined table counts the same rows.
        "desk": {"Claims intake": 2, "Loan desk": 2},
    }
    assert page.get("labels") == {"agent": {"a_claims": "Claims intake", "a_loans": "Loan desk"}}
    # The reply is the kit's model of a labelled list, whose pagination is built where `paged()` builds it.
    LabelledListResult[dict[str, Any]].model_validate(page)


async def test_the_statements_a_list_runs_do_not_grow_with_its_rows(engine: AsyncEngine) -> None:
    ran: list[str] = []

    def note(_conn: Any, _cursor: Any, statement: str, *_: Any) -> None:
        ran.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", note)
    counts: list[int] = []
    for n in (5, 50):
        await seed(engine, n)
        async with engine.connect() as c:
            ran.clear()
            page = await list_page(c, LIST, ListParams(page_size=50), **SHAPE)
            counts.append(len(ran))
        assert (len(page["data"]), page["pagination"]["total"]) == (n, n)
    # One count, one page, a GROUP BY for each of the three facets and one read of the labelled facet's names.
    assert counts == [6, 6]


async def test_ids_answer_exactly_those_rows_whatever_the_search_says(engine: AsyncEngine) -> None:
    await seed(engine, 12)
    async with engine.connect() as c:
        page = await list_page(c, LIST, ListParams(ids=["r04", "r09", "gone"], search="renewal"), **SHAPE)
    assert [r["id"] for r in page["data"]] == ["r04", "r09"] and page["pagination"]["total"] == 2


async def test_a_filter_or_sort_column_nobody_declared_is_refused() -> None:
    with pytest.raises(ValueError, match=r"store_test_list_runs\.note: declare"):
        await list_page(None, LIST, ListParams(), default_sort=runs.c.id, filters={"note": runs.c.note})  # pyright: ignore[reportArgumentType]
