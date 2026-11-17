"""The team's app cards as rows, so the Apps list pages, searches and sorts in SQL.

A card is built from the installed plugins' manifests (held in memory), the built-in app list, the team's plugin
bindings and its accounts, so no other table holds the list. Each team's rows are rebuilt from those sources when its
stamp (team_defaults.cards_stamp) differs from the install's: a write that changes which cards a team has or what one
is called (an account made, renamed, moved or deleted, a plugin turned on or off) clears the stamp in its own
transaction, and the next list rebuilds. A rebuild holds the team's team_defaults row locked from before it reads the
sources until its rows and stamp commit, so one rebuild runs at a time and a write during it, which clears the stamp
through that row, waits and leaves it cleared. A card's counts and settings are read for the page's cards only.

A row also holds what the Connected and Available tabs and the State filter need: the card's state as the team sees it
and, where each person signs in, the account whose own sign-in decides it, which the page reads for the caller from
connection_tokens in the same statement. Every write that changes a team-level input of that state (an account's
status, test or settings, the team's sign-in token, an auth config or its client secret, a plugin on or off) clears
the stamp too; a team token that ends with no way to renew sets `due_at`, and a row past it is rebuilt as a write would.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import ClassVar, TypedDict

import sqlalchemy as sa

from ops_service_kit.listing import ListParams
from ops_store import Guarantee
from ops_store.dialect import json_text, locked
from ops_store.listing import LISTED, ListPage, list_page, listed_rows
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.store import Store
from ops_store.team_scope import team_visible

from .modules import forget_cards, metadata
from .team_defaults import team_defaults
from .tenancy import ROLE

# The kind of card a built-in app is: listed only when the caller asks for the built-ins (the approval picker).
BUILTIN = "builtin"

app_cards = sa.Table(
    "app_cards",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), primary_key=True),
    # The card's id as the Apps page shows it: plugin:<id>, an account's id, builtin:<id>.
    sa.Column("id", sa.String(120), primary_key=True),
    sa.Column("kind", sa.String(16), nullable=False, info=LISTED),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("category", sa.String(120), info=LISTED),
    # The card's appState as the team sees it (apps.app_state for no person); where `own_account` is set, a person's
    # own sign-in there decides it for them instead. Null on a row built before these columns: it is rebuilt first.
    sa.Column("state", sa.String(24)),
    # How the app's default account signs in (team, person or person_or_team), when the card has one.
    sa.Column("sign_in", sa.String(16)),
    # The default account a person's own sign-in decides the state on: set once nothing before that sign-in stops it.
    sa.Column("own_account", sa.String(64)),
    # The card's default account (its `connectionId`), none when it has none: what `hasAccount` filters on.
    sa.Column("connection_id", sa.String(64)),
    # When the team token's state lapses with no write (it ends with no refresh token); the row is stale from then.
    sa.Column("due_at", sa.DateTime(timezone=True)),
    sa.Index("ix_app_cards_name", "tenant_id", "team_id", "name"),
    sa.Index("ix_app_cards_category", "tenant_id", "team_id", "category"),
    sa.Index("ix_app_cards_kind", "tenant_id", "team_id", "kind"),
    # Held to its team by the database (tools_0084): only a transaction run as ROLE in the card's team sees it.
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


class CardRow(TypedDict):
    """What a card row holds: what the list is chosen, searched and sorted by."""

    id: str
    kind: str
    name: str
    category: str | None
    state: str
    sign_in: str | None
    own_account: str | None
    connection_id: str | None
    due_at: datetime | None


# The Apps page's tabs: Connected holds the apps that work and a removed one, whose card says why its tools stopped
# (appGroup on or gone); Available every app someone still has to act on.
VIEWS = ("all", "connected", "available")
CONNECTED_STATES = ("connected", "test_failed", "removed", "not_installed")
# How the shared token row of an account is keyed in connection_tokens (store/connections.SHARED).
_TEAM_TOKEN = ""


def _tokens() -> sa.Table:
    """connection_tokens, declared in store/connections.py, which imports this module."""
    return metadata.tables["connection_tokens"]


def _connections() -> sa.Table:
    """connections, declared in store/connections.py, which imports this module."""
    return metadata.tables["connections"]


def _current(tenant_id: str, team_id: str, stamp: str, now: datetime) -> sa.ColumnElement[bool]:
    """The team's rows are current: built for `stamp`, and no row's state has lapsed by `now`."""
    t, k = team_defaults, app_cards.c
    lapsed = sa.exists().where(k.tenant_id == tenant_id, k.team_id == team_id, k.due_at <= now, team_visible(app_cards))
    return sa.and_(t.c.cards_stamp == stamp, sa.not_(lapsed))


class AppCards(Store):
    # A rebuild holds the team's defaults row locked until its rows and stamp commit.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.LOCK, Guarantee.TRANSACTION})
    role = ROLE

    async def current(self, tenant_id: str, team_id: str, stamp: str, now: datetime) -> bool:
        """Whether the team's rows are built for `stamp` and none has lapsed by `now`, read without a lock."""
        t = team_defaults
        # The condition sits in WHERE: SQL Server has no boolean value to select.
        q = sa.select(sa.literal(1)).where(
            t.c.tenant_id == tenant_id,
            t.c.team_id == team_id,
            team_visible(t),
            _current(tenant_id, team_id, stamp, now),
        )
        async with self.tx() as c:
            return (await c.execute(q)).first() is not None

    async def claim(self, tenant_id: str, team_id: str, stamp: str, now: datetime) -> bool:
        """Locks the team's defaults row until the caller's transaction ends and answers whether its rows still need
        building for `stamp`: False when another rebuild finished while this one waited. The caller reads the sources
        and calls `rebuild` in the same transaction (the request's)."""
        t = team_defaults
        q = sa.select(t.c.cards_stamp).where(t.c.tenant_id == tenant_id, t.c.team_id == team_id, team_visible(t))
        async with self.tx() as c:
            await c.execute(locked(q, t))
            return not await self.current(tenant_id, team_id, stamp, now)

    async def rebuild(self, tenant_id: str, team_id: str, cards: Sequence[CardRow], *, stamp: str) -> None:
        """Replaces the team's rows with `cards` (id, kind, name, category) and records `stamp`, under the lock `claim`
        took in the same transaction."""
        k = app_cards.c
        rows = [
            {"tenant_id": tenant_id, "team_id": team_id, "id": c["id"], "kind": c["kind"], "name": c["name"],
             "category": c["category"], "state": c["state"], "sign_in": c["sign_in"],
             "own_account": c["own_account"], "connection_id": c["connection_id"], "due_at": c["due_at"]}
            for c in cards
        ]  # fmt: skip
        t = team_defaults
        async with self.tx() as c:
            mine = (k.tenant_id == tenant_id, k.team_id == team_id, team_visible(app_cards))
            await c.execute(app_cards.delete().where(*mine))
            if rows:
                await c.execute(app_cards.insert(), rows)
            ours = (t.c.tenant_id == tenant_id, t.c.team_id == team_id, team_visible(t))
            await c.execute(t.update().where(*ours).values(cards_stamp=stamp))

    async def page(
        self, tenant_id: str, team_id: str, params: ListParams, *, builtins: bool, person: str, is_person: bool
    ) -> tuple[ListPage, dict[str, int]]:
        """One page of the team's cards by name ignoring case, then id, with the facets (appState, category, kind) and
        each tab's count over the searched and filtered cards; `search` matches the name and category, `ids` names
        cards exactly, `view` (all, connected or available) picks a tab, `accountId` keeps the cards of those
        accounts, `hasAccount` (true or false) those with or without a default account,
        `sortBy=connected` puts the connected cards first (then by name), and the built-in apps are left out
        unless `builtins`. A card's appState is the caller's: on a card whose `own_account` is set, `person`'s own
        sign-in there decides it when the app signs in per person, or per person or team and `is_person`."""
        k = app_cards.c
        tok = _tokens()
        # The caller's own sign-in on the card's default account, in the card's team: one row at most (its key).
        own = app_cards.outerjoin(
            tok,
            sa.and_(
                tok.c.tenant_id == k.tenant_id,
                tok.c.team_id == k.team_id,
                tok.c.connection_id == k.own_account,
                tok.c.person_id == person,
                team_visible(tok),
            ),
        )
        # Decided here, not in SQL: SQL Server has no boolean literal to compare.
        personal = ("person", "person_or_team") if is_person else ("person",)
        theirs = sa.and_(k.own_account.is_not(None), k.sign_in.in_(personal))
        state = sa.case(
            (sa.not_(theirs), k.state),
            (sa.or_(tok.c.person_id.is_(None), tok.c.refused_at.is_not(None)), "needs_sign_in"),
            (json_text(tok.c.test, "status") == "failed", "test_failed"),
            else_="connected",
        )
        is_on = state.in_(CONNECTED_STATES)
        views = {"all": sa.true(), "connected": is_on, "available": sa.not_(is_on)}
        view = (params.filters.get("view") or ["all"])[-1]
        q = (
            sa.select(k.id, k.kind, k.name)
            .select_from(own)
            .where(k.tenant_id == tenant_id, k.team_id == team_id, team_visible(app_cards))
        )
        if not builtins:
            q = q.where(k.kind != BUILTIN)
        if params.ids is not None:
            # The table is keyed by (tenant, team, id) and list_page's `ids` needs a one-column key, so the ids are
            # matched here: every read names one team, so an id is one row.
            q = q.where(k.id.in_(params.ids))
            params = params.model_copy(update={"ids": None, "search": None})
        if accounts := params.filters.get("accountId"):
            # The cards those accounts belong to (a connection's app_id is its card's id), in the card's team.
            a = _connections().c
            of = sa.select(a.app_id).where(
                a.tenant_id == tenant_id, a.team_id == team_id, a.id.in_(accounts), team_visible(_connections())
            )
            q = q.where(k.id.in_(of))
        # A boolean filter is its text, as list filters are: the facet counts "true" and "false".
        has_account = sa.case((k.connection_id.is_not(None), "true"), else_="false")
        facets = {"appState": state, "category": k.category, "kind": k.kind}
        # Narrows the total, the facets and the tab counts; it has no facet of its own (one more statement for two
        # values the filter already names).
        filters = {**facets, "hasAccount": has_account}
        search = [k.name, k.category]
        counting = q.with_only_columns(
            *(sa.func.sum(sa.case((cond, 1), else_=0)).label(name) for name, cond in views.items()),
            maintain_column_froms=True,
        )
        async with self.tx() as c:
            page = await list_page(
                c, q.where(views[view]), params, search=search, default_sort=sa.func.lower(k.name),
                filters=filters, facets=facets, sortable={"connected": sa.case((is_on, 1), else_=0)},
            )  # fmt: skip
            counted = (await c.execute(listed_rows(counting, params, search=search, filters=filters))).mappings().one()
        return page, {name: int(counted[name] or 0) for name in views}


# forget_cards is defined beside the modules (a module write clears the stamp too); account and binding writes import
# it from here.
__all__ = ["BUILTIN", "VIEWS", "AppCards", "CardRow", "app_cards", "forget_cards"]
