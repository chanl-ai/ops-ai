"""The threads list (`GET /v1/threads`) a page at a time in SQL, with who may read each thread in the statement.

The rule is `api.chat_threads.may_read_thread`, which the thread and event routes still apply to one row: a scoped API
key reaches its own agent or workflow only; a thread of the chat graph that names a person is read under chat.view
with that person as owner; any other thread by the team rule. The caller's chat.view scope is worked out once per
request (`ThreadReader`) and the person a thread names is worked out per row here:

- `ownerEmail` (the `owner` column, written with it) when set, else `startedFor` when it is a text value;
- a person only when that text holds an `@`; a `startedFor` that is an array or object holding an `@` names a person
  nobody is (its text matches no email), so only a reader of every chat reads that thread;
- `chat` or a legacy `owner` name make a thread a person's even when no email names one: its owner is then the
  `ownerEmail` text, else the reader whose name `owner` holds;
- a text `startedFor` over JSON_TEXT_MAX characters (with no `ownerEmail`), which SQL Server's JSON_VALUE reads as
  absent, names a person nobody is, and a legacy `owner` that long still makes the thread a person's, so a text too
  long to compare never widens who reads the thread.

Emails match stripped and lower-cased on both sides, as `ops_access.can` compares an owner. A name matches exactly:
both sides end in a sentinel, since SQL Server's `=` ignores trailing spaces under any collation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import sqlalchemy as sa

from ops_service_kit.listing import ListParams
from ops_store.dialect import JsonTextLength, json_fragment, json_text
from ops_store.listing import ListPage, list_page
from ops_store.team_scope import team_visible

from .graphs import graph_threads
from .tenancy import current_tenant, tenant_tx

# The agent graph a chat thread runs (`api.run_person.CHAT_GRAPH`).
CHAT_GRAPH = "agent_wrapper"
# SQL Server's JSON_VALUE answers NULL for a text longer than this; PostgreSQL is held to the same length.
JSON_TEXT_MAX = 4000
_END = "|"


@dataclass(frozen=True)
class ThreadReader:
    """Who reads the list, as the rule needs it. `graphs`: a scoped key's one graph (empty when its target names no
    graph), None for every other caller. `chat`: the caller's chat.view scope from `can` (`all` reads every person's
    thread, `own` its own, `none` none). `email` stripped and lower-cased; `name` as the token gives it."""

    graphs: tuple[str, ...] | None
    chat: Literal["none", "own", "all"]
    email: str
    name: str


def _ends(term: sa.ColumnElement[str], value: str) -> sa.ColumnElement[bool]:
    """`term` equals `value` exactly, trailing spaces included."""
    return term + _END == value + _END


def _same_email(term: sa.ColumnElement[str], email: str) -> sa.ColumnElement[bool]:
    return sa.func.lower(sa.func.trim(term)) == email


def readable(reader: ThreadReader) -> sa.ColumnElement[bool]:
    """The threads `reader` may read: `may_read_thread` as one predicate on `graph_threads`."""
    t = graph_threads
    terms: list[sa.ColumnElement[bool]] = []
    if reader.graphs is not None:
        terms.append(t.c.graph.in_(reader.graphs) if reader.graphs else sa.false())
    if reader.chat == "all":
        return sa.and_(*terms) if terms else sa.true()
    owner_email = sa.func.nullif(t.c.owner, "")
    raw = json_text(t.c.meta, "startedFor")
    started_for = sa.case((sa.func.length(raw) <= JSON_TEXT_MAX, sa.func.nullif(raw, "")), else_=None)
    fragment = json_fragment(t.c.meta, "startedFor")
    # An array or object: its own JSON text on both databases (JSON_VALUE answers NULL for one on SQL Server). Read by
    # its first character, not LIKE, where SQL Server takes `[` as the start of a character set.
    nested = sa.func.coalesce(sa.func.substring(fragment, 1, 1), "").in_(("[", "{"))
    # The text that decides the person: ownerEmail when set, else a text startedFor (a JSON string reads its text).
    named = sa.case((owner_email.is_not(None), owner_email), else_=sa.case((nested, None), else_=started_for))
    person = sa.case((named.like("%@%"), named), else_=None)
    # Each term below is TRUE or FALSE, never NULL, as the NOTs that use them need.
    long_started_for = sa.func.coalesce(JsonTextLength(t.c.meta, "startedFor"), 0) > JSON_TEXT_MAX
    long_owner = sa.func.coalesce(JsonTextLength(t.c.meta, "owner"), 0) > JSON_TEXT_MAX
    nobody = sa.and_(
        owner_email.is_(None),
        sa.or_(sa.and_(nested, sa.func.coalesce(fragment, "").like("%@%")), long_started_for),
    )
    chat = sa.func.coalesce(json_text(t.c.meta, "chat"), "").in_(("true", "1"))
    legacy = json_text(t.c.meta, "owner")
    flagged = sa.or_(chat, sa.func.coalesce(legacy, "") != "", long_owner)
    teams = sa.and_(person.is_(None), sa.not_(nobody), sa.not_(flagged))
    allowed: list[sa.ColumnElement[bool]] = [t.c.graph != CHAT_GRAPH, teams]
    if reader.chat == "own":
        allowed.append(sa.and_(person.is_not(None), _same_email(person, reader.email)))
        # No email names the person and `chat` or `owner` does: the ownerEmail text, else the reader `owner` names.
        unnamed = sa.and_(person.is_(None), sa.not_(nobody))
        allowed.append(sa.and_(unnamed, owner_email.is_not(None), _same_email(owner_email, reader.email)))
        if reader.email:
            allowed.append(sa.and_(unnamed, owner_email.is_(None), _ends(legacy, reader.name)))
    return sa.and_(*terms, sa.or_(*allowed))


def thread_columns(reader: ThreadReader) -> sa.Select[Any]:
    """The tenant's threads of the acting team (every team with none acting) that `reader` may read."""
    t = graph_threads
    return sa.select(t).where(t.c.tenant_id == current_tenant(), team_visible(t), readable(reader))


async def threads_page(engine: Any, params: ListParams, reader: ThreadReader) -> ListPage:
    """The threads list on the shared contract: `graph` filters, sorted by `sortBy` (updatedAt, the newest first by
    default), then by the key. `ids` names threads; `search` changes nothing."""
    t = graph_threads
    async with tenant_tx(engine) as c:
        return await list_page(
            c,
            thread_columns(reader),
            params.model_copy(update={"search": None}),
            sortable={"updatedAt": t.c.updated_at},
            default_sort=t.c.updated_at.desc(),
            filters={"graph": t.c.graph},
        )


__all__ = ["ThreadReader", "readable", "thread_columns", "threads_page"]
