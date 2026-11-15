"""One way to answer a list: the page, its total and its facet counts, all in SQL, on the caller's transaction.

  async with st.runs.tx() as conn:
      page = await list_page(conn, sa.select(*RUN_COLUMNS).where(team_visible(runs)), q,
                             search=[runs.c.title], sortable={"startedAt": runs.c.started_at},
                             default_sort=runs.c.started_at.desc(), filters={"status": runs.c.status},
                             facets={"status": runs.c.status})

`query` is the list before paging: its columns, joins and the rows the caller may see, with no GROUP BY or DISTINCT.
The statements are the same number whatever the page size: one count, one page, one GROUP BY per facet and one read
per labelled facet. A facet's counts leave its own filter out, so the other choices of the facet keep their numbers
while one is picked. A column a list filters or sorts on is declared with `info=LISTED` where its table is defined,
and `deploy/database/tests/test_indexes.py` fails when a declared column has no index.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any, NotRequired, TypedDict

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_service_kit.http import page_window
from ops_service_kit.listing import ListParams

from .search import contains

# On a column: a list filters or sorts on it, so it needs an index that leads with it.
LISTED_KEY = "ops_listed"
LISTED: dict[str, Any] = {LISTED_KEY: True}

_NONE: Mapping[str, Any] = MappingProxyType({})
# A select of any number of columns.
Rows = sa.Select[*tuple[Any, ...]]


class Pagination(TypedDict):
    page: int
    pageSize: int
    total: int
    totalPages: int
    hasNext: bool
    hasPrev: bool


class ListPage(TypedDict):
    """The `ListResult` JSON (`ops_service_kit.http`); `labels` only when the caller asked for some."""

    data: list[dict[str, Any]]
    pagination: Pagination
    facets: dict[str, dict[str, int]]
    labels: NotRequired[dict[str, dict[str, str]]]


async def list_page(
    conn: AsyncConnection,
    query: Rows,
    params: ListParams,
    *,
    search: Sequence[sa.ColumnElement[Any]] = (),
    sortable: Mapping[str, sa.ColumnElement[Any]] = _NONE,
    default_sort: sa.ColumnElement[Any],
    filters: Mapping[str, sa.ColumnElement[Any]] = _NONE,
    facets: Mapping[str, sa.ColumnElement[Any]] = _NONE,
    labels: Mapping[str, Rows] = _NONE,
) -> ListPage:
    """count(*), ORDER BY, LIMIT and OFFSET, one GROUP BY per facet, all on `query`; `labels` maps each facet value to
    its label in the same transaction. default_sort is required: SQL Server's OFFSET needs an ORDER BY.

    `search` columns are matched for `params.search`; `sortable` and `filters` name the columns `sortBy` and the other
    query keys may use, and a key they do not name is ignored; `params.ids` answers exactly those rows of `query`'s
    `id` column, whatever the search says. A `labels` entry is a select of (value, label), read for the values its
    facet counted."""
    _declared({**sortable, **filters})
    if params.ids is not None:
        chosen = [query.selected_columns["id"].in_(params.ids)]
    else:
        words = (params.search or "").strip()
        chosen = [sa.or_(*(contains(c, words) for c in search))] if words and search else []
    wanted = {key: filters[key].in_(values) for key, values in params.filters.items() if key in filters and values}
    listed = query.where(*chosen, *wanted.values())

    total = int((await conn.execute(listed.with_only_columns(sa.func.count()).order_by(None))).scalar_one())
    page, offset = page_window(total, params.page, params.page_size)
    by = sortable.get(params.sort_by or "")
    order = [by.asc() if params.sort_order == "asc" else by.desc(), default_sort] if by is not None else [default_sort]
    rows = await conn.execute(listed.order_by(None).order_by(*order).limit(params.page_size).offset(offset))

    counted: dict[str, dict[str, int]] = {}
    for name, column in facets.items():
        others = [clause for key, clause in wanted.items() if key != name]
        q = query.where(*chosen, *others).with_only_columns(column, sa.func.count()).group_by(column).order_by(None)
        counted[name] = {str(value): int(n) for value, n in await conn.execute(q) if value is not None}

    pages = max(1, -(-total // params.page_size))
    out: ListPage = {
        "data": [dict(r) for r in rows.mappings()],
        "pagination": {
            "page": page,
            "pageSize": params.page_size,
            "total": total,
            "totalPages": pages,
            "hasNext": page < pages,
            "hasPrev": page > 1,
        },
        "facets": counted,
    }
    if labels:
        out["labels"] = {
            name: await _labels(conn, read, sorted(counted.get(name, {}))) for name, read in labels.items()
        }
    return out


async def _labels(conn: AsyncConnection, read: Rows, values: list[str]) -> dict[str, str]:
    if not values:
        return {}
    value = next(iter(read.selected_columns))
    return {str(v): str(label) for v, label in await conn.execute(read.where(value.in_(values)))}


def _declared(columns: Mapping[str, sa.ColumnElement[Any]]) -> None:
    """A table column a list filters or sorts on says so where it is defined, which is what the index test reads."""
    missing = sorted(
        f"{c.table.name}.{c.name}" for c in columns.values() if isinstance(c, sa.Column) and not c.info.get(LISTED_KEY)
    )
    if missing:
        raise ValueError(f"list_page filters or sorts on {', '.join(missing)}: declare each with info=LISTED")


__all__ = ["LISTED", "LISTED_KEY", "ListPage", "Pagination", "list_page"]
