"""The console's chat list read in SQL: one page, its total and its facets, in the list's order, on PostgreSQL and
Azure SQL alike (ops_store.dialect reads the JSON fields). A thread's pinned flag, last message and the rest live in
`graph_threads.meta`; nothing here loads a thread that is not on the page.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store.dialect import json_array_has, json_fragment, json_text
from ops_store.team_scope import team_visible

from .chat_search import chat_search, matching_query
from .graphs import _mine, graph_threads
from .tenancy import tenant_tx

_T = graph_threads.c
_TRUE = ("true", "1")


def _flag(key: str) -> sa.ColumnElement[bool]:
    return sa.func.coalesce(json_text(_T.meta, key), "false").in_(_TRUE)


def pinned_flag() -> sa.ColumnElement[int]:
    return sa.case((_flag("pinned"), 1), else_=0)


def last_message_at() -> sa.ColumnElement[str]:
    return sa.func.coalesce(json_text(_T.meta, "lastMessageAt"), _T.created_at)


def state_of() -> sa.ColumnElement[str]:
    return sa.case((_flag("archived"), "archived"), (_flag("pinned"), "pinned"), else_="active")


def _agent() -> sa.ColumnElement[str]:
    return sa.func.coalesce(json_text(_T.meta, "agentId"), "None")


@dataclass(frozen=True)
class ChatListQuery:
    graph: str
    owner_email: str
    owner_name: str
    test: bool = False
    states: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    kbs: list[str] = field(default_factory=list)
    search: str | None = None
    # "default" (pinned first, then newest), "title", "createdAt", "messageCount" or "lastMessageAt".
    sort_by: str = "default"
    descending: bool = True
    pinned: bool | None = None


def _visible(q: ChatListQuery) -> list[sa.ColumnElement[bool]]:
    """The caller's own chat threads of the right kind: the owner's email, or the name on threads that predate it."""
    email = sa.func.coalesce(json_text(_T.meta, "ownerEmail"), "")
    return [
        _mine(graph_threads),
        team_visible(graph_threads),
        _T.graph == q.graph,
        _flag("chat"),
        ~_flag("hidden"),
        _flag("test") if q.test else ~_flag("test"),
        sa.or_(email == q.owner_email, sa.and_(email == "", json_text(_T.meta, "owner") == q.owner_name)),
    ]


def _selected(q: ChatListQuery) -> list[sa.ColumnElement[bool]]:
    where = _visible(q)
    if q.states:
        where.append(state_of().in_(q.states))
    if q.agents:
        where.append(_agent().in_(q.agents))
    if q.kbs:
        where.append(sa.or_(*(json_array_has(_T.meta, "kbIds", k) for k in q.kbs)))
    if q.search and q.search.strip():
        where.append(_T.id.in_(matching_query(q.search)))
    if q.pinned is not None:
        where.append(_flag("pinned") if q.pinned else ~_flag("pinned"))
    return where


def order_keys(sort_by: str) -> list[sa.ColumnElement[Any]]:
    match sort_by:
        case "title":
            return [sa.func.lower(sa.func.coalesce(json_text(_T.meta, "title"), ""))]
        case "createdAt":
            return [_T.created_at]
        case "messageCount":
            return [sa.cast(sa.func.coalesce(json_text(_T.meta, "messageCount"), "0"), sa.Integer)]
        case "lastMessageAt":
            return [last_message_at()]
        case _:
            return [pinned_flag(), last_message_at()]


def _after(keys: list[sa.ColumnElement[Any]], after: tuple[list[Any], str], descending: bool) -> sa.ColumnElement[bool]:
    """Rows past the position `after` in the order: key by key, with the id breaking ties. Written out because SQL
    Server has no row-value comparison."""
    values, thread_id = after
    cols = [*keys, _T.id]
    vals = [*values, thread_id]
    clauses: list[sa.ColumnElement[bool]] = []
    for i, col in enumerate(cols):
        ties = [cols[j] == vals[j] for j in range(i)]
        past = col < vals[i] if descending else col > vals[i]
        clauses.append(sa.and_(*ties, past))
    return sa.or_(*clauses)


@dataclass
class ChatPage:
    rows: list[dict[str, Any]]
    total: int
    more: bool
    remaining: int | None


def page_queries(
    q: ChatListQuery, *, limit: int, offset: int = 0, after: tuple[list[Any], str] | None = None
) -> tuple[sa.Select[Any], sa.Select[Any], sa.Select[Any] | None]:
    """The page (one row beyond `limit`), the count selected and, past a position, the count remaining."""
    keys = order_keys(q.sort_by)
    where = _selected(q)
    sign = (lambda c: c.desc()) if q.descending else (lambda c: c.asc())
    page = graph_threads.select().where(*where).order_by(*(sign(c) for c in (*keys, _T.id))).limit(limit + 1)
    remaining_q = None
    if after is not None:
        past = _after(keys, after, q.descending)
        page = page.where(past)
        remaining_q = sa.select(sa.func.count()).select_from(graph_threads).where(*where, past)
    else:
        page = page.offset(offset)
    return page, sa.select(sa.func.count()).select_from(graph_threads).where(*where), remaining_q


async def chat_page(
    engine: AsyncEngine,
    q: ChatListQuery,
    *,
    limit: int,
    offset: int = 0,
    after: tuple[list[Any], str] | None = None,
) -> ChatPage:
    """`limit` rows of the list in its order, from `offset` or after the position `after`, plus the number selected.
    One row beyond the page is read to know whether more follow. `remaining` counts the rows past `after`."""
    page, total_q, remaining_q = page_queries(q, limit=limit, offset=offset, after=after)
    async with tenant_tx(engine) as c:
        got = [dict(r) for r in (await c.execute(page)).mappings()]
        total = int((await c.execute(total_q)).scalar_one())
        remaining = int((await c.execute(remaining_q)).scalar_one()) if remaining_q is not None else None
    return ChatPage(got[:limit], total, len(got) > limit, remaining)


def facet_queries(q: ChatListQuery) -> dict[str, sa.Select[Any]]:
    """Per-agent and per-state counts, and the kb id arrays to tally. The grouping is a subquery's column: grouping
    by an expression with bound parameters fails on SQL Server (error 8120, the select list's parameters differ)."""
    where = _visible(q)
    base = sa.select(_agent().label("v")).where(*where).subquery()
    states = sa.select(state_of().label("v")).where(*where).subquery()
    return {
        "agentId": sa.select(base.c.v, sa.func.count()).group_by(base.c.v),
        "state": sa.select(states.c.v, sa.func.count()).group_by(states.c.v),
        "kbIds": sa.select(json_fragment(_T.meta, "kbIds")).where(*where),
    }


async def chat_facets(engine: AsyncEngine, q: ChatListQuery) -> dict[str, dict[str, int]]:
    """Counts of the caller's chats by agent, knowledge base and state, before any filter is applied."""
    queries = facet_queries(q)
    out: dict[str, dict[str, int]] = {"agentId": {}, "kbIds": {}, "state": {}}
    async with tenant_tx(engine) as c:
        for name in ("agentId", "state"):
            out[name] = {str(v): int(n) for v, n in await c.execute(queries[name])}
        for (raw,) in await c.execute(queries["kbIds"]):
            for kb in json.loads(raw) if raw else []:
                out["kbIds"][str(kb)] = out["kbIds"].get(str(kb), 0) + 1
    return out


async def unsummarised_rows(engine: AsyncEngine, q: ChatListQuery, *, limit: int) -> list[dict[str, Any]]:
    """The caller's own chat threads written before summaries or search rows were kept (no `messageCount` in meta or
    no search row), at most `limit` of them, so a list backfills a batch at a time."""
    indexed = sa.exists().where(chat_search.c.thread_id == _T.id)
    stmt = (
        graph_threads.select()
        .where(*_visible(q), sa.or_(json_text(_T.meta, "messageCount").is_(None), ~indexed))
        .limit(limit)
    )
    async with tenant_tx(engine) as c:
        return [dict(r) for r in (await c.execute(stmt)).mappings()]
