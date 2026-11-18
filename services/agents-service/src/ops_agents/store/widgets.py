"""Widget templates as versioned attachments (`docs/architecture/chat-widgets.md`): a builder lays one out
from the catalogue, it publishes through a review decided by someone other than whoever saved it, and agents pin it by
`{widgetId, version}`. Versions are immutable once published; a draft is edited in place until it is requested.
Publish requests are the registry's (`registry_publish_requests`, kind `widget`).

A version's `content`: name, useWhen, tree, dataSchema, sample. The seeded library (seed/widgets.json) stays outside
these tables and is served beside them.
"""

from __future__ import annotations

from typing import ClassVar, NotRequired, TypedDict, cast

import sqlalchemy as sa
from pydantic import BaseModel, JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_service_kit.errors import Conflict
from ops_service_kit.http import Json, JsonList, Out
from ops_service_kit.ids import now_iso
from ops_store import Guarantee, isolation
from ops_store.rows import rows
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, team_owned_via
from ops_store.search import contains
from ops_store.team_scope import any_team, team_visible

from .agent_registry import digest_of, publish_requests
from .base import metadata
from .graphs import mine
from .tenancy import OWNER, UNIQUE_KEY, current_tenant
from .versioned import VersionedRegistry

registry_widgets = sa.Table(
    "registry_widgets",
    metadata,
    # The tenant the row belongs to, the caller's on insert, with no default (agents 0109). Leads the
    # key (agents 0108): a widget id is a slug, so two tenants may choose the same one.
    sa.Column("tenant_id", sa.String(64), primary_key=True, default=current_tenant),
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
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

registry_widget_versions = sa.Table(
    "registry_widget_versions",
    metadata,
    # Its widget's tenant; the composite key below holds a version to a widget of the same tenant (agents 0108).
    sa.Column("tenant_id", sa.String(64), primary_key=True, default=current_tenant),
    sa.Column("widget_id", sa.String(64), primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("content", sa.JSON, nullable=False),
    sa.Column("digest", sa.String(64), nullable=False),
    sa.Column("changes", sa.JSON, nullable=False),
    sa.Column("saved_at", sa.String(32), nullable=False),
    sa.Column("saved_by", sa.String(200), nullable=False),
    sa.Column("published_at", sa.String(32)),
    sa.Column("published_by", sa.String(200)),
    sa.Column("review_id", sa.String(64)),
    sa.ForeignKeyConstraint(
        ["tenant_id", "widget_id"],
        ["registry_widgets.tenant_id", "registry_widgets.id"],
        name="registry_widget_versions_tenant_id_widget_id_fkey",
        ondelete="CASCADE",
        onupdate="CASCADE",
    ),
    info={**TENANT_SCOPED, **team_owned_via("registry_widgets", "widget_id")},
)


class WidgetContent(TypedDict):
    """A widget version's `content` as `api/widgets.check_content` writes it, in stored order. `sample` is optional:
    a reader that found none read it as None."""

    name: str
    useWhen: str
    tree: JsonValue
    dataSchema: JsonValue
    sample: NotRequired[JsonValue]


class ListedWidget(BaseModel):
    """A widget as the list shows it: its row with its newest version's `content` and `published_at`, and `pending`
    while a publish request for it waits."""

    id: str
    team_id: str
    version: int
    retired_reason: str | None
    updated_at: str
    updated_by: str
    content: dict[str, JsonValue]
    published_at: str | None
    pending: bool


class WidgetRow(Out):
    """A widget's row: its team, newest name and version, newest published version, and why it was retired."""

    tenant_id: str
    id: str
    team_id: str
    name: str
    version: int
    published_version: int | None
    retired_reason: str | None
    created_at: str
    updated_at: str
    updated_by: str


class WidgetVersion(Out):
    """One saved version of a widget; `content` is its layout document."""

    tenant_id: str
    widget_id: str
    version: int
    content: Json
    digest: str
    changes: JsonList
    saved_at: str
    saved_by: str
    published_at: str | None
    published_by: str | None
    review_id: str | None


LABELS = {"name": "name", "useWhen": "use-when line", "tree": "layout", "dataSchema": "data schema", "sample": "sample"}


def changes_between(old: Json, new: Json) -> list[str]:
    return [f"Changed {label}" for k, label in LABELS.items() if old.get(k) != new.get(k)]


class WidgetRegistry(VersionedRegistry[WidgetRow, WidgetVersion]):
    # An id and a version number are unique keys (CAS); a save writes its version row and moves the widget in one
    # transaction, as does a publish (TRANSACTION).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})
    head = registry_widgets
    history = registry_widget_versions
    subject = "widget_id"
    noun = "Widget"
    in_tenant = True
    head_row = WidgetRow
    version_row = WidgetVersion

    async def page(
        self, teams: list[str], search: str, offset: int, limit: int, ids: list[str] | None = None
    ) -> list[ListedWidget]:
        """One page of the widgets in `teams` whose name contains `search` (or exactly `ids`), by name then id, each
        with its newest version's content and publish time and whether a publish request for it waits; one statement,
        LIMIT and OFFSET in the query."""
        w, v, r = registry_widgets.c, registry_widget_versions.c, publish_requests.c
        waiting = (
            sa.select(r.id)
            .where(r.tenant_id == current_tenant(), r.kind == "widget", r.subject_id == w.id, r.status == "pending")
            .correlate(registry_widgets)
            .exists()
        )
        q = (
            sa.select(
                w.id,
                w.team_id,
                w.version,
                w.retired_reason,
                w.updated_at,
                w.updated_by,
                v.content,
                v.published_at,
                sa.case((waiting, 1), else_=0).label("pending"),
            )
            .join_from(
                registry_widgets,
                registry_widget_versions,
                sa.and_(v.tenant_id == w.tenant_id, v.widget_id == w.id, v.version == w.version),
            )
            .where(
                self._chosen(teams, search, ids),
                w.tenant_id == current_tenant(),
                # The versions are joined on their widget's tenant and id, so the widget's team holds them too.
                team_visible(registry_widgets),
            )
            .order_by(sa.func.lower(w.name), w.id)
            .offset(offset)
            .limit(limit)
        )
        async with self.tx() as c:
            return await rows(c, q, ListedWidget)

    async def count(self, teams: list[str], search: str, ids: list[str] | None = None) -> int:
        q = (
            sa.select(sa.func.count())
            .select_from(registry_widgets)
            .where(self._chosen(teams, search, ids), mine(registry_widgets), team_visible(registry_widgets))
        )
        async with self.tx() as c:
            return int((await c.execute(q)).scalar_one())

    @staticmethod
    def _chosen(teams: list[str], search: str, ids: list[str] | None) -> sa.ColumnElement[bool]:
        """Widgets in `teams`: exactly `ids` when given, else those whose name contains `search`."""
        named = registry_widgets.c.id.in_(ids) if ids is not None else contains(registry_widgets.c.name, search)
        return sa.and_(named, registry_widgets.c.team_id.in_(teams))

    async def owner_team(self, widget_id: str, conn: AsyncConnection | None = None) -> str | None:
        """The team that owns it, whoever is acting; None when there is none. Only for deciding a refusal by the
        owning team, never for showing the record."""
        return (await self.owner_teams(conn, registry_widgets, {widget_id}, OWNER)).get(widget_id)

    async def create(self, widget_id: str, content: WidgetContent | Json, *, team_id: str, by: str) -> None:
        at = now_iso()
        async with self.tx() as c:
            taken = sa.select(registry_widgets.c.id).where(
                mine(registry_widgets),
                registry_widgets.c.id == widget_id,
                any_team(registry_widgets, "a widget id is unique across the tenant's teams"),
            )
            # The team policy shows a team only its own rows; the id is unique across the tenant's teams.
            async with isolation.tenant_wide_on(c, UNIQUE_KEY) as wide:
                held = (await wide.execute(taken)).first()
            if held is not None:
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
                    digest=digest_of(cast(Json, content)),
                    changes=["Created"],
                    saved_at=at,
                    saved_by=by,
                )
            )

    async def save_draft(self, widget_id: str, content: WidgetContent | Json, *, by: str) -> int:
        """Edits the newest version while it is an unpublished draft, or opens the next version on top of a published
        one. Published versions never change."""
        at = now_iso()
        async with self.tx() as c:
            n = (await self.row(widget_id, c)).version
            newest = await self.newest(c, widget_id, n)
            values = {"content": content, "digest": digest_of(cast(Json, content)), "saved_at": at, "saved_by": by}
            if newest.published_at is None:
                await c.execute(
                    registry_widget_versions.update()
                    .where(
                        mine(registry_widget_versions),
                        registry_widget_versions.c.widget_id == widget_id,
                        registry_widget_versions.c.version == n,
                    )
                    .values(**values, changes=changes_between(newest.content, cast(Json, content)) or ["No change"])
                )
            else:
                n += 1
                await c.execute(
                    registry_widget_versions.insert().values(
                        widget_id=widget_id,
                        version=n,
                        changes=changes_between(newest.content, cast(Json, content)),
                        **values,
                    )
                )
            await c.execute(
                registry_widgets.update()
                .where(mine(registry_widgets), registry_widgets.c.id == widget_id)
                .values(version=n, name=str(content["name"]), updated_at=at, updated_by=by)
            )
        return n

    async def publish(self, widget_id: str, version: int, *, by: str, review_id: str) -> None:
        at = now_iso()
        async with self.tx() as c:
            await c.execute(
                registry_widget_versions.update()
                .where(
                    mine(registry_widget_versions),
                    registry_widget_versions.c.widget_id == widget_id,
                    registry_widget_versions.c.version == version,
                )
                .values(published_at=at, published_by=by, review_id=review_id)
            )
            await c.execute(
                registry_widgets.update()
                .where(mine(registry_widgets), registry_widgets.c.id == widget_id)
                .values(published_version=version, updated_at=at, updated_by=by)
            )

    async def retire(self, widget_id: str, reason: str, *, by: str) -> None:
        async with self.tx() as c:
            await self.row(widget_id, c)
            await c.execute(
                registry_widgets.update()
                .where(mine(registry_widgets), registry_widgets.c.id == widget_id)
                .values(retired_reason=reason, updated_at=now_iso(), updated_by=by)
            )
