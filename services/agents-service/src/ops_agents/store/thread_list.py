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


def _true(meta: sa.ColumnElement[Any], key: str) -> sa.ColumnElement[bool]:
    """Python reads `meta[key]` as true: present and not null, false, a zero number, an empty text, list or object.
    Strings are told apart from numbers and booleans by their length (`JsonTextLength`, NULL for any other value), so
    the text `"0"` is true and the number 0 is not; an empty text by its length, as SQL Server's `=` ignores trailing
    spaces. Never NULL."""
    size = JsonTextLength(meta, key)
    text = json_text(meta, key)
    fragment = json_fragment(meta, key)
    # A JSON number whose only digits are 0 is zero, whatever its sign, point or exponent.
    digits: sa.ColumnElement[str] = text
    for c in ("0", ".", "-", "+", "e", "E"):
        digits = sa.func.replace(digits, c, "")
    present = sa.or_(size.is_not(None), text.is_not(None), sa.and_(fragment.is_not(None), fragment != "null"))
    empty = sa.or_(
        sa.func.coalesce(size, -1) == 0,
        sa.and_(size.is_(None), text.is_not(None), sa.or_(text == "false", sa.and_(text != "true", digits == ""))),
        sa.func.coalesce(sa.func.replace(fragment, " ", ""), "").in_(("[]", "{}")),
    )
    return sa.and_(present, sa.not_(empty))


@dataclass(frozen=True)
class _Named:
    """What one metadata field says of the person a thread names: `person` the text when it is a text holding an `@`
    and short enough to read, else NULL; `nobody` TRUE when it names a person nobody is (a list or object holding an
    `@`, whose text matches no email, or a text too long to read), else FALSE."""

    person: sa.ColumnElement[str]
    nobody: sa.ColumnElement[bool]


def _named(meta: sa.ColumnElement[Any], key: str) -> _Named:
    size = sa.func.coalesce(JsonTextLength(meta, key), -1)
    text = json_text(meta, key)
    fragment = json_fragment(meta, key)
    # An array or object: its own JSON text on both databases (JSON_VALUE answers NULL for one on SQL Server). Read by
    # its first character, not LIKE, where SQL Server takes `[` as the start of a character set.
    nested = sa.func.coalesce(sa.func.substring(fragment, 1, 1), "").in_(("[", "{"))
    readable_text = sa.and_(size >= 0, size <= JSON_TEXT_MAX)
    person = sa.case((sa.and_(readable_text, text.like("%@%")), text), else_=None)
    nobody = sa.or_(sa.and_(nested, sa.func.coalesce(fragment, "").like("%@%")), size > JSON_TEXT_MAX)
    return _Named(person, nobody)


def readable(reader: ThreadReader) -> sa.ColumnElement[bool]:
    """The threads `reader` may read: `may_read_thread` as one predicate on `graph_threads`, read from the metadata as
    the Python rule reads it (never the `owner` column, which a row may lack)."""
    t = graph_threads
    terms: list[sa.ColumnElement[bool]] = []
    if reader.graphs is not None:
        terms.append(t.c.graph.in_(reader.graphs) if reader.graphs else sa.false())
    if reader.chat == "all":
        return sa.and_(*terms) if terms else sa.true()
    # ownerEmail decides the person when Python reads it as true, else startedFor (`run_person.person_of_thread`).
    has_owner_email = _true(t.c.meta, "ownerEmail")
    by_email, by_start = _named(t.c.meta, "ownerEmail"), _named(t.c.meta, "startedFor")
    person = sa.case((has_owner_email, by_email.person), else_=by_start.person)
    # Each term below is TRUE or FALSE, never NULL, as the NOTs that use them need. A predicate, not a CASE: SQL Server
    # takes no condition as a CASE's value.
    nobody = sa.or_(sa.and_(has_owner_email, by_email.nobody), sa.and_(sa.not_(has_owner_email), by_start.nobody))
    flagged = sa.or_(_true(t.c.meta, "chat"), _true(t.c.meta, "owner"))
    teams = sa.and_(person.is_(None), sa.not_(nobody), sa.not_(flagged))
    allowed: list[sa.ColumnElement[bool]] = [t.c.graph != CHAT_GRAPH, teams]
    if reader.chat == "own":
        allowed.append(sa.and_(person.is_not(None), _same_email(person, reader.email)))
        # No email names the person and `chat` or `owner` does: the ownerEmail text, else the reader `owner` names.
        unnamed = sa.and_(person.is_(None), sa.not_(nobody))
        owner_email = json_text(t.c.meta, "ownerEmail")
        allowed.append(sa.and_(unnamed, has_owner_email, _same_email(owner_email, reader.email)))
        if reader.email:
            # Python compares `owner` to the name, so only a text `owner` can match.
            legacy = sa.and_(
                JsonTextLength(t.c.meta, "owner").is_not(None), _ends(json_text(t.c.meta, "owner"), reader.name)
            )
            allowed.append(sa.and_(unnamed, sa.not_(has_owner_email), legacy))
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
