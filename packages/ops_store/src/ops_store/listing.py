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

A list over several sources is a select from a UNION ALL of one select per source, each with the same column names and
a source tag, made a subquery; `key` names the result columns that tell its rows apart:

  sources = sa.union_all(
      sa.select(sa.literal("mailbox").label("source"), mailboxes.c.id, mailboxes.c.name).where(team_visible(mailboxes)),
      sa.select(sa.literal("embed").label("source"), embeds.c.id, embeds.c.title.label("name"))
      .where(team_visible(embeds)),
  ).subquery("channels")
  page = await list_page(conn, sa.select(sources), q, key=(sources.c.source, sources.c.id),
                         search=[sources.c.name], default_sort=sources.c.name, facets={"source": sources.c.source})

The helper adds no tenant or team predicate to a union: each branch carries its own, written in the same function as
the union so `tests/test_team_reads.py` sees the table and its `team_visible` together. No branch has an ORDER BY.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, NotRequired, TypedDict, cast

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection
from sqlalchemy.sql import operators

from ops_service_kit.http import PageJSON, page_window, paged
from ops_service_kit.listing import ListParams

from . import isolation
from .search import contains

# On a column: a list filters or sorts on it, so it needs an index that leads with it.
LISTED_KEY = "ops_listed"
LISTED: dict[str, Any] = {LISTED_KEY: True}

_NONE: Mapping[str, Any] = MappingProxyType({})
# A select of any number of columns.
Rows = sa.Select[*tuple[Any, ...]]


@dataclass(frozen=True)
class Several:
    """A field a row holds several values of (a source's tags on each of its documents), as a filter and a facet:
    `values` selects (key, value) pairs, one per value a row holds, and `key` is the column of the list's query the
    pairs' key names a row by. The filter keeps a row holding any value asked for; the facet counts each value once
    per row holding it, so a row counts under each of its values and once in the total."""

    key: sa.ColumnElement[Any]
    values: Rows


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
    several: Mapping[str, Several] = _NONE,
    key: Sequence[sa.ColumnElement[Any]] = (),
) -> ListPage:
    """count(*), ORDER BY, LIMIT and OFFSET, one GROUP BY per facet, all on `query`; `labels` maps each facet value to
    its label in the same transaction. default_sort is required: SQL Server's OFFSET needs an ORDER BY.

    The order always ends with the primary key of `query`'s first table, in the main sort's direction (`sortBy`'s
    when given, else default_sort's), unless the order already names every key column. Without it, rows that share
    a sort value come back in any order, so they repeat or vanish between pages.

    `search` columns are matched for `params.search`; `sortable` and `filters` name the columns `sortBy` and the other
    query keys may use, and a key they do not name is ignored; `params.ids` answers exactly those rows by the
    primary key of `query`'s first table, whatever the search says, with the context's tenant for a (tenant_id, id) key
    (a key of more than one other column raises ValueError).
    A `labels` entry is a select of (value, label), read for the values its facet counted. A `several` entry is a
    filter and a facet of a field each row holds several values of (`Several`). A facet may be an expression (a CASE
    of a code's label): it is grouped by name in a subquery, which SQL Server needs when the expression has bound
    values.

    `key` replaces the primary key, for the order's last terms and for `ids`, and is required when `query` selects
    from a union (see the module docstring): a union's subquery carries its first branch's key, which two sources share.
    `ids` name the key's last column, so an id two sources share answers both rows; the tenant is not added to it."""
    key = _key(query, key)
    _declared({**sortable, **filters, **{name: f.key for name, f in several.items()}}, key)
    chosen, wanted = _narrowing(query, params, search, filters, several, row_key=key)
    listed = query.where(*chosen, *wanted.values())

    # The FROM is kept: a table only the columns named would drop with them and the count would be one row.
    counting = listed.with_only_columns(sa.func.count(), maintain_column_froms=True).order_by(None)
    total = int((await conn.execute(counting)).scalar_one())
    page, offset = page_window(total, params.page, params.page_size)
    by = sortable.get(params.sort_by or "")
    if by is not None:
        descending = params.sort_order != "asc"
        # SQL Server refuses an ORDER BY that names a column twice, so the default sort is left out when it is sortBy's.
        order = [by.desc() if descending else by.asc()]
        order += [default_sort] if _column(default_sort) is not _column(by) else []
    else:
        descending = isinstance(default_sort, sa.UnaryExpression) and default_sort.modifier is operators.desc_op
        order = [default_sort]
    order += _key_order(query, order, descending, key)
    rows = await conn.execute(listed.order_by(None).order_by(*order).limit(params.page_size).offset(offset))

    counted: dict[str, dict[str, int]] = {}
    for name, column in facets.items():
        others = [clause for key, clause in wanted.items() if key != name]
        inner = query.where(*chosen, *others).with_only_columns(column.label("value"), maintain_column_froms=True)
        grouped = inner.order_by(None).subquery()
        q = sa.select(grouped.c.value, sa.func.count()).group_by(grouped.c.value)
        counted[name] = {str(value): int(n) for value, n in await conn.execute(q) if value is not None}
    for name, field in several.items():
        others = [clause for key, clause in wanted.items() if key != name]
        keys = query.where(*chosen, *others).with_only_columns(field.key.label("key"), maintain_column_froms=True)
        listed_keys = keys.order_by(None).subquery()
        pairs = _pairs(field)
        q = (
            sa.select(pairs.c.value, sa.func.count())
            .select_from(listed_keys.join(pairs, pairs.c.key == listed_keys.c.key))
            .group_by(pairs.c.value)
        )
        counted[name] = {str(value): int(n) for value, n in await conn.execute(q) if value is not None}

    named = {name: await _labels(conn, read, sorted(counted.get(name, {}))) for name, read in labels.items()}
    data = [dict(r) for r in rows.mappings()]
    out = paged(data, total, page, params.page_size, facets=counted, labels=named or None)
    return cast(ListPage, out)


def listed_rows(
    query: Rows,
    params: ListParams,
    *,
    search: Sequence[sa.ColumnElement[Any]] = (),
    filters: Mapping[str, sa.ColumnElement[Any]] = _NONE,
    several: Mapping[str, Several] = _NONE,
    key: Sequence[sa.ColumnElement[Any]] = (),
) -> Rows:
    """`query` narrowed exactly as `list_page` narrows it before counting and paging (`ids`, else the search, and the
    filters), for a caller that needs another aggregate over the same rows, such as a count per view:

      rows = listed_rows(sa.select(sa.func.count()).select_from(files).where(*base), q, search=..., filters=FACETS)
      quarantined = (await conn.execute(rows.where(files.c.scan_status == "infected"))).scalar_one()
    """
    key = _key(query, key)
    _declared({**filters, **{name: f.key for name, f in several.items()}}, key)
    chosen, wanted = _narrowing(query, params, search, filters, several, row_key=key)
    return query.where(*chosen, *wanted.values())


def _narrowing(
    query: Rows,
    params: ListParams,
    search: Sequence[sa.ColumnElement[Any]],
    filters: Mapping[str, sa.ColumnElement[Any]],
    several: Mapping[str, Several] = _NONE,
    *,
    row_key: Sequence[sa.ColumnElement[Any]] = (),
) -> tuple[list[sa.ColumnElement[bool]], dict[str, sa.ColumnElement[bool]]]:
    """The rows asked for (`ids`, else the search) and each filter by its key, kept apart so a facet can leave its
    own filter out."""
    chosen: list[sa.ColumnElement[bool]]
    if params.ids is not None:
        chosen = [row_key[-1].in_(params.ids)] if row_key else _picked(query, params.ids)
    else:
        words = (params.search or "").strip()
        chosen = [sa.or_(*(contains(c, words) for c in search))] if words and search else []
    wanted: dict[str, sa.ColumnElement[bool]] = {
        key: filters[key].in_(values) for key, values in params.filters.items() if key in filters and values
    }
    for key, values in params.filters.items():
        if key in several and values:
            pairs = _pairs(several[key])
            wanted[key] = several[key].key.in_(sa.select(pairs.c.key).where(pairs.c.value.in_(values)))
    return chosen, wanted


def _pairs(field: Several) -> sa.Subquery:
    """A `Several`'s (key, value) pairs by those names, each pair once, so a row counts once under a value."""
    key, value = list(field.values.selected_columns)[:2]
    return field.values.with_only_columns(key.label("key"), value.label("value")).distinct().subquery()


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


def _key(query: Rows, key: Sequence[sa.ColumnElement[Any]]) -> list[sa.ColumnElement[Any]]:
    """The declared key, refused when absent for a union, whose subquery's key is its first branch's alone."""
    if isinstance(query, sa.CompoundSelect):
        raise ValueError("list_page over a union: pass sa.select(<union>.subquery(name)) and key=(source, id)")
    if key:
        return list(key)
    table = _first_table(query)
    if isinstance(getattr(table, "element", None), sa.CompoundSelect):
        raise ValueError(
            f"list_page over the union {table.name}: pass key=(source, id), the result columns that tell its rows "
            "apart; its own key is its first branch's, which another source's ids repeat"
        )
    return []


def _picked(query: Rows, ids: list[str]) -> list[sa.ColumnElement[bool]]:
    """The rows `ids` names by the first table's primary key, since some tables are keyed by a name. For a key of
    (tenant_id, id) the caller passes the id part and the tenant is the isolation context's, so the statement names
    whole keys and the key's index serves it. With no tenant in force (an install-wide block, a system read before its
    tenant is known) the id part alone is matched."""
    table = _first_table(query)
    key = [c for c in table.primary_key.columns if c.name != "tenant_id"]
    if len(key) != 1:
        names = ", ".join(c.name for c in key)
        raise ValueError(f"list_page ids: {table.name} is keyed by ({names}); ids needs a key of one column")
    picked = [key[0].in_(ids)]
    if "tenant_id" in table.primary_key.columns:
        with suppress(isolation.NoTenantError):
            picked.append(table.c.tenant_id == isolation.tenant())
    return picked


def _key_order(
    query: Rows, order: list[sa.ColumnElement[Any]], descending: bool, declared: list[sa.ColumnElement[Any]]
) -> list[sa.ColumnElement[Any]]:
    """The declared key, else the primary key of the query's first table, as the last ORDER BY terms, so every row
    has one place."""
    named = {_column(term) for term in order}
    key = declared or list(_first_table(query).primary_key.columns)
    # A key column the order already names is left out: SQL Server refuses an ORDER BY that names a column twice.
    return [c.desc() if descending else c.asc() for c in key if c not in named]


def _column(term: sa.ColumnElement[Any]) -> Any:
    """The column under a term's ASC, DESC or label."""
    while isinstance(term, sa.UnaryExpression | sa.Label):
        term = term.element
    return term


def _declared(columns: Mapping[str, sa.ColumnElement[Any]], key: Sequence[sa.ColumnElement[Any]] = ()) -> None:
    """A table column a list filters or sorts on says so where it is defined, which is what the index test reads. A
    primary key column is its key's index's. A column of the keyed result (a union's) has no definition to say it on;
    naming it in the call declares it."""
    result = {id(_column(k).table) for k in key if isinstance(_column(k), sa.ColumnClause)}
    missing = sorted(
        f"{c.table.name}.{c.name}"
        for c in columns.values()
        if isinstance(c, sa.Column) and not c.primary_key and not c.info.get(LISTED_KEY) and id(c.table) not in result
    )
    if missing:
        raise ValueError(f"list_page filters or sorts on {', '.join(missing)}: declare each with info=LISTED")


__all__ = ["LISTED", "LISTED_KEY", "ListPage", "Several", "list_page", "listed_rows"]
