"""Widget templates as versioned attachments (c-082, `docs/architecture/chat-widgets.md`): a builder lays one out
from the catalogue, it publishes through a review decided by someone other than whoever saved it, and agents pin it by
`{widgetId, version}`. Versions are immutable once published; a draft is edited in place until it is requested.
Publish requests are the registry's (`registry_publish_requests`, kind `widget`).

A version's `content`: name, useWhen, tree, dataSchema, sample. The seeded library (seed/widgets.json) stays outside
these tables and is served beside them.
"""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.errors import Conflict, NotFound
from ops_service_kit.ids import now_iso
from ops_store import Guarantee
from ops_store.schema import TEAM_OWNED, team_owned_via
from ops_store.search import contains
from ops_store.team_scope import any_team, team_visible

from .agent_registry import digest_of
from .base import metadata

registry_widgets = sa.Table(
    "registry_widgets",
    metadata,
    # The widget id agents pin, a slug of its first name (hold-review).
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    # The newest version's name, kept on the row so the list searches and pages it in the query.
    sa.Column("name", sa.String(200), nullable=False, server_default=""),
    # Newest saved version, draft or published.
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("published_version", sa.Integer),
    # Set once with a reason; terminal. Pins already on agents keep working; new pins are refused.
    sa.Column("retired_reason", sa.Text),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False),
    sa.Column("updated_by", sa.String(200), nullable=False),
    info=TEAM_OWNED,
)

registry_widget_versions = sa.Table(
    "registry_widget_versions",
    metadata,
    sa.Column("widget_id", sa.String(64), sa.ForeignKey("registry_widgets.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("content", sa.JSON, nullable=False),
    sa.Column("digest", sa.String(64), nullable=False),
    sa.Column("changes", sa.JSON, nullable=False),
    sa.Column("saved_at", sa.String(32), nullable=False),
    sa.Column("saved_by", sa.String(200), nullable=False),
    sa.Column("published_at", sa.String(32)),
    sa.Column("published_by", sa.String(200)),
    sa.Column("review_id", sa.String(64)),
    info=team_owned_via("registry_widgets", "widget_id"),
)

LABELS = {"name": "name", "useWhen": "use-when line", "tree": "layout", "dataSchema": "data schema", "sample": "sample"}


def changes_between(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    return [f"Changed {label}" for k, label in LABELS.items() if old.get(k) != new.get(k)]


class WidgetRegistry:
    # An id and a version number are unique keys (CAS); a save writes its version row and moves the widget in one
    # transaction, as does a publish (TRANSACTION).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def rows(self) -> list[dict[str, Any]]:
        async with self.engine.connect() as c:
            return [
                dict(r)
                for r in (
                    await c.execute(
                        sa.select(registry_widgets)
                        .where(team_visible(registry_widgets))
                        .order_by(registry_widgets.c.id)
                    )
                ).mappings()
            ]

    async def page(self, teams: list[str], search: str, offset: int, limit: int) -> list[dict[str, Any]]:
        """One page of the widgets in `teams` whose name contains `search`, by name; LIMIT and OFFSET run in the
        query."""
        q = (
            sa.select(registry_widgets)
            .where(self._matches(teams, search), team_visible(registry_widgets))
            .order_by(sa.func.lower(registry_widgets.c.name), registry_widgets.c.id)
        )
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q.offset(offset).limit(limit))).mappings()]

    async def pinnable(
        self, teams: list[str], search: str, offset: int, limit: int, ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Widgets an agent may newly pin (published, not retired) in `teams`, by name, searched and limited in the
        query; `ids` returns exactly those in `teams`, so a pin already held keeps its label."""
        t = registry_widgets.c
        scope = t.team_id.in_(teams)
        if ids is not None:
            q = sa.select(registry_widgets).where(scope, t.id.in_(ids), team_visible(registry_widgets))
        else:
            q = sa.select(registry_widgets).where(
                self._matches(teams, search),
                t.published_version.is_not(None),
                t.retired_reason.is_(None),
                team_visible(registry_widgets),
            )
        q = q.order_by(sa.func.lower(t.name), t.id).offset(offset).limit(limit)
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def count(self, teams: list[str], search: str) -> int:
        q = (
            sa.select(sa.func.count())
            .select_from(registry_widgets)
            .where(self._matches(teams, search), team_visible(registry_widgets))
        )
        async with self.engine.connect() as c:
            return int((await c.execute(q)).scalar_one())

    @staticmethod
    def _matches(teams: list[str], search: str) -> sa.ColumnElement[bool]:
        return sa.and_(contains(registry_widgets.c.name, search), registry_widgets.c.team_id.in_(teams))

    async def owner_team(self, widget_id: str) -> str | None:
        """The team that owns it, whoever is acting; None when there is none. Only for deciding a refusal by the
        owning team, never for showing the record."""
        q = sa.select(registry_widgets.c.team_id).where(
            registry_widgets.c.id == widget_id, any_team(registry_widgets, "the owning team a refusal is decided on")
        )
        async with self.engine.connect() as c:
            team = (await c.execute(q)).scalar()
        return str(team) if team else None

    async def find(self, widget_id: str, c: AsyncConnection | None = None) -> dict[str, Any] | None:
        q = sa.select(registry_widgets).where(registry_widgets.c.id == widget_id, team_visible(registry_widgets))
        if c is not None:
            r = (await c.execute(q)).mappings().first()
        else:
            async with self.engine.connect() as conn:
                r = (await conn.execute(q)).mappings().first()
        return dict(r) if r else None

    async def row(self, widget_id: str, c: AsyncConnection | None = None) -> dict[str, Any]:
        r = await self.find(widget_id, c)
        if r is None:
            raise NotFound(f"Widget {widget_id}")
        return r

    async def version(self, widget_id: str, version: int) -> dict[str, Any] | None:
        async with self.engine.connect() as c:
            q = sa.select(registry_widget_versions).where(
                registry_widget_versions.c.widget_id == widget_id,
                registry_widget_versions.c.version == version,
                team_visible(registry_widget_versions),
            )
            r = (await c.execute(q)).mappings().first()
            return dict(r) if r else None

    async def versions(self, widget_id: str) -> list[dict[str, Any]]:
        async with self.engine.connect() as c:
            q = (
                sa.select(registry_widget_versions)
                .where(registry_widget_versions.c.widget_id == widget_id, team_visible(registry_widget_versions))
                .order_by(registry_widget_versions.c.version.desc())
            )
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def create(self, widget_id: str, content: dict[str, Any], *, team_id: str, by: str) -> None:
        at = now_iso()
        async with self.engine.begin() as c:
            taken = sa.select(registry_widgets.c.id).where(
                registry_widgets.c.id == widget_id,
                any_team(registry_widgets, "a widget id is unique across every team"),
            )
            if (await c.execute(taken)).first() is not None:
                raise Conflict(f"A widget with id {widget_id} exists; rename it.", code="widget_taken")
            await c.execute(
                registry_widgets.insert().values(
                    id=widget_id,
                    team_id=team_id,
                    name=str(content["name"]),
                    version=1,
                    created_at=at,
                    updated_at=at,
                    updated_by=by,
                )
            )
            await c.execute(
                registry_widget_versions.insert().values(
                    widget_id=widget_id,
                    version=1,
                    content=content,
                    digest=digest_of(content),
                    changes=["Created"],
                    saved_at=at,
                    saved_by=by,
                )
            )

    async def save_draft(self, widget_id: str, content: dict[str, Any], *, by: str) -> int:
        """Edits the newest version while it is an unpublished draft, or opens the next version on top of a published
        one. Published versions never change."""
        at = now_iso()
        async with self.engine.begin() as c:
            n = int((await self.row(widget_id, c))["version"])
            q = sa.select(registry_widget_versions).where(
                registry_widget_versions.c.widget_id == widget_id,
                registry_widget_versions.c.version == n,
                team_visible(registry_widget_versions),
            )
            newest = (await c.execute(q)).mappings().one()
            values = {"content": content, "digest": digest_of(content), "saved_at": at, "saved_by": by}
            if newest["published_at"] is None:
                await c.execute(
                    registry_widget_versions.update()
                    .where(registry_widget_versions.c.widget_id == widget_id, registry_widget_versions.c.version == n)
                    .values(**values, changes=changes_between(newest["content"], content) or ["No change"])
                )
            else:
                n += 1
                await c.execute(
                    registry_widget_versions.insert().values(
                        widget_id=widget_id, version=n, changes=changes_between(newest["content"], content), **values
                    )
                )
            await c.execute(
                registry_widgets.update()
                .where(registry_widgets.c.id == widget_id)
                .values(version=n, name=str(content["name"]), updated_at=at, updated_by=by)
            )
        return n

    async def publish(self, widget_id: str, version: int, *, by: str, review_id: str) -> None:
        at = now_iso()
        async with self.engine.begin() as c:
            await c.execute(
                registry_widget_versions.update()
                .where(registry_widget_versions.c.widget_id == widget_id, registry_widget_versions.c.version == version)
                .values(published_at=at, published_by=by, review_id=review_id)
            )
            await c.execute(
                registry_widgets.update()
                .where(registry_widgets.c.id == widget_id)
                .values(published_version=version, updated_at=at, updated_by=by)
            )

    async def retire(self, widget_id: str, reason: str, *, by: str) -> None:
        async with self.engine.begin() as c:
            await self.row(widget_id, c)
            await c.execute(
                registry_widgets.update()
                .where(registry_widgets.c.id == widget_id)
                .values(retired_reason=reason, updated_at=now_iso(), updated_by=by)
            )
