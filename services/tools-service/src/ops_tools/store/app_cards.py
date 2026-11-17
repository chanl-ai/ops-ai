"""The team's app cards as rows, so the Apps list pages, searches and sorts in SQL.

A card is built from the installed plugins' manifests (held in memory), the built-in app list, the team's plugin
bindings and its accounts, so no other table holds the list. Each team's rows are rebuilt from those sources when its
stamp (team_defaults.cards_stamp) differs from the install's: a write that changes which cards a team has or what one
is called (an account made, renamed, moved or deleted, a plugin turned on or off) clears the stamp in its own
transaction, and the next list rebuilds. A rebuild holds the team's team_defaults row locked from before it reads the
sources until its rows and stamp commit, so one rebuild runs at a time and a write during it, which clears the stamp
through that row, waits and leaves it cleared. A card's state, counts and settings are read for the page's cards only.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar, TypedDict

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_service_kit.listing import ListParams
from ops_store import Guarantee
from ops_store.dialect import locked
from ops_store.listing import ListPage, list_page
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.store import Store
from ops_store.team_scope import team_visible

from .modules import metadata
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
    sa.Column("kind", sa.String(16), nullable=False),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("category", sa.String(120)),
    sa.Index("ix_app_cards_name", "tenant_id", "team_id", "name"),
    # Held to its team by the database (tools_0084): only a transaction run as ROLE in the card's team sees it.
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


class CardRow(TypedDict):
    """What a card row holds: what the list is chosen, searched and sorted by."""

    id: str
    kind: str
    name: str
    category: str | None


async def forget_cards(c: AsyncConnection, tenant_id: str, team: sa.ColumnElement[bool]) -> None:
    """Clears the stamp of the teams `team` names, in the caller's transaction, so their next list rebuilds."""
    t = team_defaults
    await c.execute(t.update().where(t.c.tenant_id == tenant_id, team, team_visible(t)).values(cards_stamp=None))


class AppCards(Store):
    # A rebuild holds the team's defaults row locked until its rows and stamp commit.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.LOCK, Guarantee.TRANSACTION})
    role = ROLE

    async def stamp(self, tenant_id: str, team_id: str) -> str | None:
        """The install stamp the team's rows were last built for, read without a lock; None when they need building."""
        t = team_defaults
        q = sa.select(t.c.cards_stamp).where(t.c.tenant_id == tenant_id, t.c.team_id == team_id, team_visible(t))
        async with self.tx() as c:
            return (await c.execute(q)).scalar()

    async def claim(self, tenant_id: str, team_id: str, stamp: str) -> bool:
        """Locks the team's defaults row until the caller's transaction ends and answers whether its rows still need
        building for `stamp`: False when another rebuild finished while this one waited. The caller reads the sources
        and calls `rebuild` in the same transaction (the request's)."""
        t = team_defaults
        q = sa.select(t.c.cards_stamp).where(t.c.tenant_id == tenant_id, t.c.team_id == team_id, team_visible(t))
        async with self.tx() as c:
            return (await c.execute(locked(q, t))).scalar() != stamp

    async def rebuild(self, tenant_id: str, team_id: str, cards: Sequence[CardRow], *, stamp: str) -> None:
        """Replaces the team's rows with `cards` (id, kind, name, category) and records `stamp`, under the lock `claim`
        took in the same transaction."""
        k = app_cards.c
        rows = [
            {"tenant_id": tenant_id, "team_id": team_id, "id": c["id"], "kind": c["kind"], "name": c["name"],
             "category": c["category"]}
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

    async def page(self, tenant_id: str, team_id: str, params: ListParams, *, builtins: bool) -> ListPage:
        """One page of the team's cards by name ignoring case, then id; `search` matches the name and category, `ids`
        names cards exactly, and the built-in apps are left out unless `builtins`."""
        k = app_cards.c
        q = sa.select(k.id, k.kind, k.name).where(
            k.tenant_id == tenant_id, k.team_id == team_id, team_visible(app_cards)
        )
        if not builtins:
            q = q.where(k.kind != BUILTIN)
        if params.ids is not None:
            # The table is keyed by (tenant, team, id) and list_page's `ids` needs a one-column key, so the ids are
            # matched here: every read names one team, so an id is one row.
            q = q.where(k.id.in_(params.ids))
            params = params.model_copy(update={"ids": None, "search": None})
        async with self.tx() as c:
            return await list_page(c, q, params, search=[k.name, k.category], default_sort=sa.func.lower(k.name))
