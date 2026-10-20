"""Guardrails as versioned attachments (c-063): a rule written once, owned by a team, reviewed at publish, and pinned
on agents by `{guardrailId, version}` like a skill pin. Versions are immutable; a pin names a published version.

Kind `blocked_topics` only today: `config = {topics: [str], message: str}`. The kind column leaves room for others.
Publish requests are the registry's (`registry_publish_requests`, kind `guardrail`).
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.errors import NotFound
from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee
from ops_store.schema import TEAM_OWNED, team_owned_via
from ops_store.search import contains
from ops_store.team_scope import any_team, team_visible

from .agent_registry import digest_of
from .base import metadata

registry_guardrails = sa.Table(
    "registry_guardrails",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("slug", sa.String(120), nullable=False, unique=True),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("kind", sa.String(32), nullable=False),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("owner", sa.String(200), nullable=False),
    # Newest saved version, draft or published.
    sa.Column("version", sa.Integer, nullable=False),
    # Newest published version; null until the first publish.
    sa.Column("published_version", sa.Integer),
    # live | deprecated: a deprecated guardrail takes no new pins; pins already on agents keep working.
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False),
    info=TEAM_OWNED,
)

registry_guardrail_versions = sa.Table(
    "registry_guardrail_versions",
    metadata,
    sa.Column(
        "guardrail_id", sa.String(64), sa.ForeignKey("registry_guardrails.id", ondelete="CASCADE"), primary_key=True
    ),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("config", sa.JSON, nullable=False),
    sa.Column("digest", sa.String(64), nullable=False),
    sa.Column("note", sa.Text, nullable=False, default=""),
    sa.Column("saved_at", sa.String(32), nullable=False),
    sa.Column("saved_by", sa.String(200), nullable=False),
    sa.Column("published_at", sa.String(32)),
    sa.Column("published_by", sa.String(200)),
    sa.Column("review_id", sa.String(64)),
    info=team_owned_via("registry_guardrails", "guardrail_id"),
)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "guardrail"


class GuardrailRegistry:
    # A slug and a version number are unique keys (CAS); a save writes its version row and moves the guardrail in one
    # transaction, as does a publish (TRANSACTION).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def rows(self) -> list[dict[str, Any]]:
        async with self.engine.connect() as c:
            q = (
                sa.select(registry_guardrails)
                .where(team_visible(registry_guardrails))
                .order_by(registry_guardrails.c.name)
            )
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def pinnable(
        self, search: str, offset: int, limit: int, ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Guardrails an agent may newly pin (live, with a published version), by name, searched and limited in the
        query; `ids` returns exactly those, whatever their state, so a pin already held keeps its label."""
        t = registry_guardrails.c
        if ids is not None:
            q = sa.select(registry_guardrails).where(t.id.in_(ids), team_visible(registry_guardrails))
        else:
            q = sa.select(registry_guardrails).where(
                t.status == "live",
                t.published_version.is_not(None),
                self._matches(search),
                team_visible(registry_guardrails),
            )
        q = q.order_by(sa.func.lower(t.name), t.id).offset(offset).limit(limit)
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def page(self, search: str, offset: int, limit: int) -> list[dict[str, Any]]:
        """One page of the guardrails whose name or owner contains `search`, by name; LIMIT and OFFSET run in the
        query, so a page reads only its own rows."""
        q = (
            sa.select(registry_guardrails)
            .where(self._matches(search), team_visible(registry_guardrails))
            .order_by(sa.func.lower(registry_guardrails.c.name), registry_guardrails.c.id)
        )
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q.offset(offset).limit(limit))).mappings()]

    async def count(self, search: str) -> int:
        q = (
            sa.select(sa.func.count())
            .select_from(registry_guardrails)
            .where(self._matches(search), team_visible(registry_guardrails))
        )
        async with self.engine.connect() as c:
            return int((await c.execute(q)).scalar_one())

    @staticmethod
    def _matches(search: str) -> sa.ColumnElement[bool]:
        t = registry_guardrails.c
        return sa.or_(contains(t.name, search), contains(t.owner, search))

    async def owner_team(self, guardrail_id: str) -> str | None:
        """The team that owns it, whoever is acting; None when there is none. Only for deciding a refusal by the
        owning team, never for showing the record."""
        q = sa.select(registry_guardrails.c.team_id).where(
            registry_guardrails.c.id == guardrail_id,
            any_team(registry_guardrails, "the owning team a refusal is decided on"),
        )
        async with self.engine.connect() as c:
            team = (await c.execute(q)).scalar()
        return str(team) if team else None

    async def find(self, guardrail_id: str, c: AsyncConnection | None = None) -> dict[str, Any] | None:
        q = sa.select(registry_guardrails).where(
            registry_guardrails.c.id == guardrail_id, team_visible(registry_guardrails)
        )
        if c is None:
            async with self.engine.connect() as conn:
                r = (await conn.execute(q)).mappings().first()
        else:
            r = (await c.execute(q)).mappings().first()
        return dict(r) if r else None

    async def row(self, guardrail_id: str, c: AsyncConnection | None = None) -> dict[str, Any]:
        r = await self.find(guardrail_id, c)
        if r is None:
            raise NotFound(f"Guardrail {guardrail_id}")
        return r

    async def versions(self, guardrail_id: str) -> list[dict[str, Any]]:
        q = (
            sa.select(registry_guardrail_versions)
            .where(
                registry_guardrail_versions.c.guardrail_id == guardrail_id, team_visible(registry_guardrail_versions)
            )
            .order_by(registry_guardrail_versions.c.version.desc())
        )
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def version(self, guardrail_id: str, version: int) -> dict[str, Any] | None:
        q = sa.select(registry_guardrail_versions).where(
            registry_guardrail_versions.c.guardrail_id == guardrail_id,
            registry_guardrail_versions.c.version == version,
            team_visible(registry_guardrail_versions),
        )
        async with self.engine.connect() as c:
            r = (await c.execute(q)).mappings().first()
        return dict(r) if r else None

    async def create(
        self,
        *,
        name: str,
        kind: str,
        config: dict[str, Any],
        owner: str,
        team_id: str,
        by: str,
        guardrail_id: str | None = None,
        published: bool = False,
    ) -> str:
        gid = guardrail_id or new_id("gr")
        at = now_iso()
        async with self.engine.begin() as c:
            base, n = _slug(name), 2
            slug = base
            taken = {
                str(s)
                for s in (
                    await c.execute(
                        sa.select(registry_guardrails.c.slug).where(
                            registry_guardrails.c.slug.like(f"{base}%"),
                            any_team(registry_guardrails, "a slug is unique across every team"),
                        )
                    )
                ).scalars()
            }
            while slug in taken:
                slug, n = f"{base}-{n}", n + 1
            await c.execute(
                registry_guardrails.insert().values(
                    id=gid,
                    slug=slug,
                    name=name,
                    kind=kind,
                    team_id=team_id,
                    owner=owner,
                    version=1,
                    published_version=1 if published else None,
                    status="live",
                    created_at=at,
                    updated_at=at,
                )
            )
            await c.execute(
                registry_guardrail_versions.insert().values(
                    guardrail_id=gid,
                    version=1,
                    config=config,
                    digest=digest_of(config),
                    note="Seeded" if published else "",
                    saved_at=at,
                    saved_by=by,
                    published_at=at if published else None,
                    published_by=by if published else None,
                )
            )
        return gid

    async def save(self, guardrail_id: str, config: dict[str, Any], *, by: str, note: str = "") -> int:
        """Saves `config` as the next version, a draft; pins and the published pointer do not move."""
        at = now_iso()
        async with self.engine.begin() as c:
            row = await self.row(guardrail_id, c)
            n = int(row["version"]) + 1
            await c.execute(
                registry_guardrail_versions.insert().values(
                    guardrail_id=guardrail_id,
                    version=n,
                    config=config,
                    digest=digest_of(config),
                    note=note,
                    saved_at=at,
                    saved_by=by,
                )
            )
            await c.execute(
                registry_guardrails.update()
                .where(registry_guardrails.c.id == guardrail_id)
                .values(version=n, updated_at=at)
            )
        return n

    async def publish(self, guardrail_id: str, version: int, *, by: str, review_id: str) -> None:
        at = now_iso()
        async with self.engine.begin() as c:
            await c.execute(
                registry_guardrail_versions.update()
                .where(
                    registry_guardrail_versions.c.guardrail_id == guardrail_id,
                    registry_guardrail_versions.c.version == version,
                )
                .values(published_at=at, published_by=by, review_id=review_id)
            )
            await c.execute(
                registry_guardrails.update()
                .where(registry_guardrails.c.id == guardrail_id)
                .values(published_version=version, updated_at=at)
            )

    async def set_status(self, guardrail_id: str, status: str) -> None:
        async with self.engine.begin() as c:
            await c.execute(
                registry_guardrails.update()
                .where(registry_guardrails.c.id == guardrail_id)
                .values(status=status, updated_at=now_iso())
            )

    async def delete(self, guardrail_id: str) -> None:
        async with self.engine.begin() as c:
            await self.row(guardrail_id, c)
            await c.execute(registry_guardrails.delete().where(registry_guardrails.c.id == guardrail_id))
