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
from typing import Any, NotRequired, TypedDict, cast

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql import operators

from ops_service_kit.http import PageJSON, page_window, paged
from ops_service_kit.listing import ListParams

from .search import contains

# On a column: a list filters or sorts on it, so it needs an index that leads with it.
LISTED_KEY = "ops_listed"
LISTED: dict[str, Any] = {LISTED_KEY: True}

_NONE: Mapping[str, Any] = MappingProxyType({})
# A select of any number of columns.
Rows = sa.Select[*tuple[Any, ...]]


class ListPage(TypedDict):
    """The `ListResult` JSON (`ops_service_kit.http`), or `LabelledListResult` when the caller asked for labels."""

    data: list[dict[str, Any]]
    pagination: PageJSON
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

    The order always ends with the primary key of `query`'s first table, in the main sort's direction (`sortBy`'s
    when given, else default_sort's), unless the order already names every key column. Without it, rows that share
    a sort value come back in any order, so they repeat or vanish between pages.

    `search` columns are matched for `params.search`; `sortable` and `filters` name the columns `sortBy` and the other
    query keys may use, and a key they do not name is ignored; `params.ids` answers exactly those rows by the
    primary key of `query`'s first table, whatever the search says (a key of more than one column raises ValueError).
    A `labels` entry is a select of (value, label), read for the values its facet counted."""
    _declared({**sortable, **filters})
    if params.ids is not None:
        chosen = [_id_column(query).in_(params.ids)]
    else:
        words = (params.search or "").strip()
        chosen = [sa.or_(*(contains(c, words) for c in search))] if words and search else []
    wanted = {key: filters[key].in_(values) for key, values in params.filters.items() if key in filters and values}
    listed = query.where(*chosen, *wanted.values())

    # The FROM is kept: a table only the columns named would drop with them and the count would be one row.
    counting = listed.with_only_columns(sa.func.count(), maintain_column_froms=True).order_by(None)
    total = int((await conn.execute(counting)).scalar_one())
    page, offset = page_window(total, params.page, params.page_size)
    by = sortable.get(params.sort_by or "")
    if by is not None:
        descending = params.sort_order != "asc"
        order = [by.desc() if descending else by.asc(), default_sort]
    else:
        descending = isinstance(default_sort, sa.UnaryExpression) and default_sort.modifier is operators.desc_op
        order = [default_sort]
    order += _key_order(query, order, descending)
    rows = await conn.execute(listed.order_by(None).order_by(*order).limit(params.page_size).offset(offset))

    counted: dict[str, dict[str, int]] = {}
    for name, column in facets.items():
        others = [clause for key, clause in wanted.items() if key != name]
        q = query.where(*chosen, *others).with_only_columns(column, sa.func.count(), maintain_column_froms=True)
        q = q.group_by(column).order_by(None)
        counted[name] = {str(value): int(n) for value, n in await conn.execute(q) if value is not None}

    named = {name: await _labels(conn, read, sorted(counted.get(name, {}))) for name, read in labels.items()}
    data = [dict(r) for r in rows.mappings()]
    out = paged(data, total, page, params.page_size, facets=counted, labels=named or None)
    return cast(ListPage, out)


async def _labels(conn: AsyncConnection, read: Rows, values: list[str]) -> dict[str, str]:
    if not values:
        return {}
    value = next(iter(read.selected_columns))
    return {str(v): str(label) for v, label in await conn.execute(read.where(value.in_(values)))}


def _first_table(query: Rows) -> Any:
    table: Any = query.get_final_froms()[0]
    while isinstance(table, sa.Join):
        table = table.left
    return table


def _id_column(query: Rows) -> sa.ColumnElement[Any]:
    """The one column `ids` names a row by: the first table's primary key, since some tables are keyed by a name."""
    table = _first_table(query)
    key = list(table.primary_key.columns)
    if len(key) != 1:
        raise ValueError(f"list_page ids: {table.name} has a primary key of {len(key)} columns; ids needs one")
    return key[0]


def _key_order(query: Rows, order: list[sa.ColumnElement[Any]], descending: bool) -> list[sa.ColumnElement[Any]]:
    """The primary key of the query's first table, as the last ORDER BY terms, so every row has one place."""
    table = _first_table(query)
    named = {_column(term) for term in order}
    key = list(table.primary_key.columns)
    if not key or all(c in named for c in key):
        return []
    return [c.desc() if descending else c.asc() for c in key]


def _column(term: sa.ColumnElement[Any]) -> Any:
    """The column under a term's ASC, DESC or label."""
    while isinstance(term, sa.UnaryExpression | sa.Label):
        term = term.element
    return term


def _declared(columns: Mapping[str, sa.ColumnElement[Any]]) -> None:
    """A table column a list filters or sorts on says so where it is defined, which is what the index test reads."""
    missing = sorted(
        f"{c.table.name}.{c.name}" for c in columns.values() if isinstance(c, sa.Column) and not c.info.get(LISTED_KEY)
    )
    if missing:
        raise ValueError(f"list_page filters or sorts on {', '.join(missing)}: declare each with info=LISTED")


__all__ = ["LISTED", "LISTED_KEY", "ListPage", "list_page"]
