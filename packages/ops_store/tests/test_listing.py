"""`list_page` on each database, by failure mode: a page counted or cut in Python, a page past the end answering
nothing, a facet that loses its other choices once one is picked, statements that grow with the rows, a search
narrowing the rows a picker asked for by id, a filter column nobody declared, and rows sharing a sort value that
repeat or vanish between pages."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Literal

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
    sa.Column("at", sa.DateTime, nullable=False, info=LISTED),
    sa.Index("ix_store_test_list_runs_status", "status"),
)
# Keyed by name, as a model alias is: no `id` column.
aliases = sa.Table(
    "store_test_list_aliases",
    meta,
    sa.Column("name", sa.String(32), primary_key=True),
    sa.Column("target", sa.String(32), nullable=False),
)
# Keyed by tenant and id, as most tenant tables are: the tenant is the caller's, so `id` names the row.
types = sa.Table(
    "store_test_list_types",
    meta,
    sa.Column("tenant_id", sa.String(32), primary_key=True),
    sa.Column("id", sa.String(32), primary_key=True),
)
# Keyed by two columns besides the tenant: `ids` cannot name one row.
pairs = sa.Table(
    "store_test_list_pairs",
    meta,
    sa.Column("tenant", sa.String(32), primary_key=True),
    sa.Column("name", sa.String(32), primary_key=True),
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


AT = datetime(2026, 11, 16, 9, 30)


def rows(n: int) -> list[dict[str, Any]]:
    """Run r01..: every third is held, the rest open; odd ones are Claims intake's; one in four is titled a refund."""
    return [
        {
            "id": f"r{i:02d}",
            "title": f"{'Refund' if i % 4 == 0 else 'Renewal'} {i:02d}",
            "status": "held" if i % 3 == 0 else "open",
            "agent_id": "a_claims" if i % 2 else "a_loans",
            "minutes": 100 - i,
            "at": AT,
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
            await c.execute(aliases.insert(), [{"name": f"alias-{i}", "target": f"model-{i}"} for i in range(1, 6)])
            await c.execute(types.insert(), [{"tenant_id": "t1", "id": i} for i in ("invoice", "receipt", "claim")])
        yield e
        async with e.begin() as c:
            await c.run_sync(meta.drop_all)
        await e.dispose()


async def seed(engine: AsyncEngine, n: int, *, shuffled: bool = False) -> None:
    """`shuffled` inserts out of id order, so a database answering ties in insertion order is not id order by luck."""
    made = sorted(rows(n), key=lambda r: int(r["id"][1:]) * 37 % 61) if shuffled else rows(n)
    async with engine.begin() as c:
        await c.execute(runs.delete())
        await c.execute(runs.insert(), made)


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


async def test_a_list_with_no_filter_counts_every_row_whether_or_not_it_joins(engine: AsyncEngine) -> None:
    """A count that keeps only the columns' FROM drops a table that only the columns named, so it counts one row."""
    await seed(engine, 5)
    joined = sa.select(runs.c.id).join(agents, agents.c.id == runs.c.agent_id)
    async with engine.connect() as c:
        alone = await list_page(
            c, sa.select(aliases.c.name, aliases.c.target), ListParams(), default_sort=aliases.c.name
        )
        both = await list_page(c, joined, ListParams(), default_sort=runs.c.id, facets={"desk": agents.c.name})
    assert (alone["pagination"]["total"], len(alone["data"])) == (5, 5)
    assert (both["pagination"]["total"], len(both["data"])) == (5, 5)
    assert both["facets"] == {"desk": {"Claims intake": 3, "Loan desk": 2}}


async def test_ids_pick_rows_by_the_primary_key_and_refuse_a_key_of_two_columns(engine: AsyncEngine) -> None:
    async with engine.connect() as c:
        page = await list_page(
            c, sa.select(aliases.c.target), ListParams(ids=["alias-2", "alias-4", "gone"]), default_sort=aliases.c.name
        )
        assert [r["target"] for r in page["data"]] == ["model-2", "model-4"] and page["pagination"]["total"] == 2
        picked = sa.select(types.c.id).where(types.c.tenant_id == "t1")
        page = await list_page(c, picked, ListParams(ids=["claim", "invoice"]), default_sort=types.c.id)
        assert [r["id"] for r in page["data"]] == ["claim", "invoice"]
        with pytest.raises(ValueError, match="store_test_list_pairs"):
            await list_page(c, sa.select(pairs.c.name), ListParams(ids=["x"]), default_sort=pairs.c.name)


async def test_sorting_by_the_default_sort_column_names_it_once(engine: AsyncEngine) -> None:
    """SQL Server refuses an ORDER BY that names a column twice."""
    await seed(engine, 4)
    asked = ListParams(sort_by="minutes", sort_order="asc")
    async with engine.connect() as c:
        page = await list_page(c, LIST, asked, sortable={"minutes": runs.c.minutes}, default_sort=runs.c.minutes.desc())
    assert [r["id"] for r in page["data"]] == ["r04", "r03", "r02", "r01"]


async def test_rows_sharing_a_sort_value_appear_once_across_pages_ordered_by_primary_key(engine: AsyncEngine) -> None:
    await seed(engine, 60, shuffled=True)
    ids = sorted(r["id"] for r in rows(60))
    held = [i for i in ids if int(i[1:]) % 3 == 0]
    opened = [i for i in ids if int(i[1:]) % 3]
    cases: list[tuple[Any, str | None, Literal["asc", "desc"], list[str]]] = [
        (runs.c.at.desc(), None, "desc", ids[::-1]),
        (runs.c.at.asc(), None, "asc", ids),
        # sortBy on a column with two values: the default sort ties too, so the key follows sortBy's direction.
        (runs.c.at.desc(), "status", "asc", held + opened),
        (runs.c.at.desc(), "status", "desc", opened[::-1] + held[::-1]),
    ]
    for default_sort, sort_by, order, expected in cases:
        for _ in range(2):
            seen: list[str] = []
            async with engine.connect() as c:
                for n in (1, 2, 3):
                    asked = ListParams(page=n, page_size=20, sort_by=sort_by, sort_order=order)
                    page = await list_page(
                        c, LIST, asked, sortable={"status": runs.c.status}, default_sort=default_sort
                    )
                    seen += [r["id"] for r in page["data"]]
            assert seen == expected, (sort_by, order)


async def test_a_filter_or_sort_column_nobody_declared_is_refused() -> None:
    with pytest.raises(ValueError, match=r"store_test_list_runs\.note: declare"):
        await list_page(None, LIST, ListParams(), default_sort=runs.c.id, filters={"note": runs.c.note})  # pyright: ignore[reportArgumentType]
