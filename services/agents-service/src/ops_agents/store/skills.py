"""Skills as versioned attachments (spec 11, c-063 slice 2): a procedure written once, published through a review, and
pinned on agents by `{skillId, version}`. Versions are immutable once published; a draft is edited in place until it
is requested. Publish requests are the registry's (`registry_publish_requests`, kind `skill`).

A version's `content`: name, slug, useWhen, loading (`on_match` | `always`), instructions, toolIds, knowledgeBases,
guardrails. `tokens` is what the body adds to a turn when loaded.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.errors import Conflict, NotFound
from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee
from ops_store.schema import TEAM_OWNED, team_owned_via
from ops_store.search import contains
from ops_store.team_scope import any_team, team_visible

from .agent_registry import digest_of
from .base import metadata

registry_skills = sa.Table(
    "registry_skills",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("slug", sa.String(64), nullable=False, unique=True),
    sa.Column("owner_team", sa.String(200), nullable=False),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("origin", sa.String(16), nullable=False),
    # Newest saved version, draft or published.
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("published_version", sa.Integer),
    # Set once with a reason; terminal. Pins already on agents keep working; new pins are refused.
    sa.Column("deprecated_reason", sa.Text),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False),
    sa.Column("updated_by", sa.String(200), nullable=False),
    # Who created the skill, written once; delete rights read it (version 1's saved_by changes with each draft save).
    sa.Column("created_by", sa.String(200), nullable=False, server_default=""),
    # The published version's loading (on_match or always), kept on the row so the agent page's picker filters it in
    # the query; null until a first publish.
    sa.Column("published_loading", sa.String(16)),
    info=TEAM_OWNED,
)

registry_skill_versions = sa.Table(
    "registry_skill_versions",
    metadata,
    sa.Column("skill_id", sa.String(64), sa.ForeignKey("registry_skills.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("content", sa.JSON, nullable=False),
    sa.Column("digest", sa.String(64), nullable=False),
    sa.Column("tokens", sa.Integer, nullable=False),
    sa.Column("note", sa.Text, nullable=False, default=""),
    sa.Column("changes", sa.JSON, nullable=False),
    sa.Column("saved_at", sa.String(32), nullable=False),
    sa.Column("saved_by", sa.String(200), nullable=False),
    sa.Column("published_at", sa.String(32)),
    sa.Column("published_by", sa.String(200)),
    sa.Column("review_id", sa.String(64)),
    info=team_owned_via("registry_skills", "skill_id"),
)


def slug_of(name: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "skill")[:64].rstrip("-")


LABELS = {
    "name": "name",
    "slug": "slug",
    "useWhen": "use-when line",
    "loading": "loading",
    "instructions": "instructions",
    "toolIds": "tools",
    "knowledgeBases": "knowledge bases",
    "guardrails": "guardrails",
}


def changes_between(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    return [f"Changed {label}" for k, label in LABELS.items() if old.get(k) != new.get(k)]


def tokens_of(content: dict[str, Any]) -> int:
    """What the body adds to a turn, at four characters a token: the instructions plus the guardrail lines."""
    lines: list[Any] = list(content.get("guardrails") or [])
    text = str(content.get("instructions") or "") + "".join(str(g) for g in lines)
    return max(1, (len(text) + 3) // 4)


class SkillRegistry:
    # A slug and a version number are unique keys (CAS); a save writes its version and moves the skill in one
    # transaction, as does a publish (TRANSACTION).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def rows(self) -> list[dict[str, Any]]:
        async with self.engine.connect() as c:
            q = sa.select(registry_skills).where(team_visible(registry_skills)).order_by(registry_skills.c.slug)
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def attachable(
        self,
        search: str,
        held: list[str],
        offset: int,
        limit: int,
        *,
        ids: list[str] | None = None,
        loading: str | None = None,
    ) -> list[dict[str, Any]]:
        """Published, live skills an agent does not hold, by slug (the name in URL form, which the search is turned
        into), searched and limited in the query; `ids` returns exactly those."""
        t = registry_skills.c
        if ids is not None:
            q = sa.select(registry_skills).where(t.id.in_(ids), team_visible(registry_skills))
        else:
            q = sa.select(registry_skills).where(
                team_visible(registry_skills),
                t.published_version.is_not(None),
                t.deprecated_reason.is_(None),
                t.id.not_in(held) if held else sa.true(),
                contains(t.slug, slug_of(search) if search.strip() else ""),
                t.published_loading == loading if loading else sa.true(),
            )
        q = q.order_by(t.slug).offset(offset).limit(limit)
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def owner_team(self, skill_id: str) -> str | None:
        """The team that owns it, whoever is acting; None when there is none. Only for deciding a refusal by the
        owning team, never for showing the record."""
        q = sa.select(registry_skills.c.team_id).where(
            registry_skills.c.id == skill_id, any_team(registry_skills, "the owning team a refusal is decided on")
        )
        async with self.engine.connect() as c:
            team = (await c.execute(q)).scalar()
        return str(team) if team else None

    async def find(self, skill_id: str, c: AsyncConnection | None = None) -> dict[str, Any] | None:
        q = sa.select(registry_skills).where(registry_skills.c.id == skill_id, team_visible(registry_skills))
        if c is None:
            async with self.engine.connect() as conn:
                r = (await conn.execute(q)).mappings().first()
        else:
            r = (await c.execute(q)).mappings().first()
        return dict(r) if r else None

    async def row(self, skill_id: str, c: AsyncConnection | None = None) -> dict[str, Any]:
        r = await self.find(skill_id, c)
        if r is None:
            raise NotFound(f"Skill {skill_id}")
        return r

    async def versions(self, skill_id: str) -> list[dict[str, Any]]:
        q = (
            sa.select(registry_skill_versions)
            .where(registry_skill_versions.c.skill_id == skill_id, team_visible(registry_skill_versions))
            .order_by(registry_skill_versions.c.version.desc())
        )
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def version(self, skill_id: str, version: int) -> dict[str, Any] | None:
        q = sa.select(registry_skill_versions).where(
            registry_skill_versions.c.skill_id == skill_id,
            registry_skill_versions.c.version == version,
            team_visible(registry_skill_versions),
        )
        async with self.engine.connect() as c:
            r = (await c.execute(q)).mappings().first()
        return dict(r) if r else None

    async def create(
        self,
        content: dict[str, Any],
        *,
        owner_team: str,
        team_id: str,
        origin: str,
        by: str,
        skill_id: str | None = None,
        published: bool = False,
    ) -> str:
        sid = skill_id or new_id("sk")
        at = now_iso()
        async with self.engine.begin() as c:
            taken = (
                await c.execute(
                    sa.select(registry_skills.c.id).where(
                        registry_skills.c.slug == content["slug"],
                        any_team(registry_skills, "a slug is unique across every team"),
                    )
                )
            ).first()
            if taken is not None:
                raise Conflict(f"The slug {content['slug']} is taken; rename the skill.", code="slug_taken")
            await c.execute(
                registry_skills.insert().values(
                    id=sid,
                    slug=content["slug"],
                    owner_team=owner_team,
                    team_id=team_id,
                    origin=origin,
                    version=1,
                    published_version=1 if published else None,
                    created_at=at,
                    updated_at=at,
                    updated_by=by,
                    created_by=by,
                )
            )
            await c.execute(
                registry_skill_versions.insert().values(
                    skill_id=sid,
                    version=1,
                    content=content,
                    digest=digest_of(content),
                    tokens=tokens_of(content),
                    note="Seeded" if published else "",
                    changes=["Created"],
                    saved_at=at,
                    saved_by=by,
                    published_at=at if published else None,
                    published_by=by if published else None,
                )
            )
        return sid

    async def save_draft(self, skill_id: str, content: dict[str, Any], *, by: str, note: str) -> int:
        """Edits the newest version while it is an unpublished draft, or opens the next version on top of a published
        one. Published versions never change."""
        at = now_iso()
        async with self.engine.begin() as c:
            row = await self.row(skill_id, c)
            n = int(row["version"])
            newest = (
                (
                    await c.execute(
                        sa.select(registry_skill_versions).where(
                            registry_skill_versions.c.skill_id == skill_id,
                            registry_skill_versions.c.version == n,
                            team_visible(registry_skill_versions),
                        )
                    )
                )
                .mappings()
                .one()
            )
            values = {
                "content": content,
                "digest": digest_of(content),
                "tokens": tokens_of(content),
                "note": note,
                "saved_at": at,
                "saved_by": by,
            }
            if newest["published_at"] is None:
                await c.execute(
                    registry_skill_versions.update()
                    .where(registry_skill_versions.c.skill_id == skill_id, registry_skill_versions.c.version == n)
                    .values(**values, changes=changes_between(newest["content"], content) or ["No change"])
                )
            else:
                n += 1
                await c.execute(
                    registry_skill_versions.insert().values(
                        skill_id=skill_id,
                        version=n,
                        changes=changes_between(newest["content"], content),
                        **values,
                    )
                )
            await c.execute(
                registry_skills.update()
                .where(registry_skills.c.id == skill_id)
                .values(version=n, slug=content["slug"], updated_at=at, updated_by=by)
            )
        return n

    async def publish(self, skill_id: str, version: int, *, by: str, review_id: str) -> None:
        at = now_iso()
        async with self.engine.begin() as c:
            await c.execute(
                registry_skill_versions.update()
                .where(registry_skill_versions.c.skill_id == skill_id, registry_skill_versions.c.version == version)
                .values(published_at=at, published_by=by, review_id=review_id)
            )
            content = (
                await c.execute(
                    sa.select(registry_skill_versions.c.content).where(
                        registry_skill_versions.c.skill_id == skill_id,
                        registry_skill_versions.c.version == version,
                        team_visible(registry_skill_versions),
                    )
                )
            ).scalar_one()
            await c.execute(
                registry_skills.update()
                .where(registry_skills.c.id == skill_id)
                .values(
                    published_version=version,
                    published_loading=str(dict(content).get("loading") or "on_match"),
                    updated_at=at,
                    updated_by=by,
                )
            )

    async def deprecate(self, skill_id: str, reason: str, *, by: str) -> None:
        async with self.engine.begin() as c:
            await c.execute(
                registry_skills.update()
                .where(registry_skills.c.id == skill_id)
                .values(deprecated_reason=reason, updated_at=now_iso(), updated_by=by)
            )

    async def delete(self, skill_id: str) -> None:
        async with self.engine.begin() as c:
            await self.row(skill_id, c)
            await c.execute(registry_skills.delete().where(registry_skills.c.id == skill_id))
