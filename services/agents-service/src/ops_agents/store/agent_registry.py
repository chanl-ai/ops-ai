"""The agent registry's tables and queries: agents, their immutable versions, and publish requests shared with
workflows. `api/agent_registry.py` decides what is live and builds the console's views."""

from __future__ import annotations

import hashlib
import re
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.errors import Conflict, NotFound
from ops_service_kit.ids import canonical_json, new_id, now_iso
from ops_store import Guarantee

from .base import metadata

registry_agents = sa.Table(
    "registry_agents",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("slug", sa.String(120), nullable=False, unique=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("owner", sa.String(200), nullable=False),
    # Newest saved version, draft or published.
    sa.Column("version", sa.Integer, nullable=False),
    # The version the runtime serves; null until the first publish.
    sa.Column("published_version", sa.Integer),
    sa.Column("paused", sa.Boolean, nullable=False, default=False),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False),
)

registry_agent_versions = sa.Table(
    "registry_agent_versions",
    metadata,
    sa.Column("agent_id", sa.String(64), sa.ForeignKey("registry_agents.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("spec", sa.JSON, nullable=False),
    sa.Column("digest", sa.String(64), nullable=False),
    sa.Column("note", sa.Text, nullable=False, default=""),
    sa.Column("changes", sa.JSON, nullable=False),
    sa.Column("saved_at", sa.String(32), nullable=False),
    sa.Column("saved_by", sa.String(200), nullable=False),
    sa.Column("published_at", sa.String(32)),
    sa.Column("published_by", sa.String(200)),
    sa.Column("review_id", sa.String(64)),
)

publish_requests = sa.Table(
    "registry_publish_requests",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("kind", sa.String(16), nullable=False),  # agent | workflow
    sa.Column("subject_id", sa.String(64), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("status", sa.String(16), nullable=False),  # pending | approved | rejected | returned
    sa.Column("note", sa.Text, nullable=False),
    sa.Column("requested_by", sa.String(200), nullable=False),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("decided_at", sa.String(32)),
    sa.Column("decided_by", sa.String(200)),
    sa.Column("decision_reason", sa.Text),
    sa.Column("body", sa.JSON, nullable=False),
)
sa.Index("ix_registry_publish_requests_subject", publish_requests.c.kind, publish_requests.c.subject_id)

SPEC_FIELDS = ("name", "role", "model", "owner", "channels", "instructions", "toolIds", "collections", "guardrails")


def digest_of(spec: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(spec).encode()).hexdigest()


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "agent"


def changes_between(old: dict[str, Any] | None, new: dict[str, Any]) -> list[str]:
    if old is None:
        return ["Created"]
    labels = {"toolIds": "tools", "collections": "knowledge bases"}
    return [f"Changed {labels.get(k, k)}" for k in SPEC_FIELDS if old.get(k) != new.get(k)] or ["No changes"]


class AgentRegistry:
    # A slug and a version number are unique keys (CAS); a save writes its version row and moves the agent in one
    # transaction, as does a publish (TRANSACTION). Only one publish request per subject may be pending (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def rows(self) -> list[dict[str, Any]]:
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(sa.select(registry_agents))).mappings()]

    async def row(self, agent_id: str, c: AsyncConnection | None = None) -> dict[str, Any]:
        q = sa.select(registry_agents).where(registry_agents.c.id == agent_id)
        if c is None:
            async with self.engine.connect() as conn:
                r = (await conn.execute(q)).mappings().first()
        else:
            r = (await c.execute(q)).mappings().first()
        if r is None:
            raise NotFound(f"Agent {agent_id}")
        return dict(r)

    async def versions(self, agent_id: str) -> list[dict[str, Any]]:
        q = (
            sa.select(registry_agent_versions)
            .where(registry_agent_versions.c.agent_id == agent_id)
            .order_by(registry_agent_versions.c.version.desc())
        )
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def version(self, agent_id: str, version: int) -> dict[str, Any]:
        q = sa.select(registry_agent_versions).where(
            registry_agent_versions.c.agent_id == agent_id, registry_agent_versions.c.version == version
        )
        async with self.engine.connect() as c:
            r = (await c.execute(q)).mappings().first()
        if r is None:
            raise NotFound(f"Agent {agent_id} version {version}")
        return dict(r)

    async def requests(self, kind: str, subject_id: str) -> list[dict[str, Any]]:
        q = (
            sa.select(publish_requests)
            .where(publish_requests.c.kind == kind, publish_requests.c.subject_id == subject_id)
            .order_by(publish_requests.c.created_at.desc())
        )
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def _unique_slug(self, c: AsyncConnection, name: str) -> str:
        base = slugify(name)
        taken = {
            str(s)
            for s in (
                await c.execute(sa.select(registry_agents.c.slug).where(registry_agents.c.slug.like(f"{base}%")))
            ).scalars()
        }
        n, slug = 2, base
        while slug in taken:
            slug, n = f"{base}-{n}", n + 1
        return slug

    async def create(
        self,
        spec: dict[str, Any],
        *,
        by: str,
        team_id: str,
        agent_id: str | None = None,
        version: int = 1,
        published: bool = False,
    ) -> str:
        aid = agent_id or new_id("ag")
        at = now_iso()
        async with self.engine.begin() as c:
            slug = await self._unique_slug(c, spec["name"])
            await c.execute(
                registry_agents.insert().values(
                    id=aid,
                    slug=slug,
                    team_id=team_id,
                    owner=spec["owner"],
                    version=version,
                    published_version=version if published else None,
                    paused=False,
                    created_at=at,
                    updated_at=at,
                )
            )
            await c.execute(
                registry_agent_versions.insert().values(
                    agent_id=aid,
                    version=version,
                    spec=spec,
                    digest=digest_of(spec),
                    note="Seeded" if published else "",
                    changes=["Created"],
                    saved_at=at,
                    saved_by=by,
                    published_at=at if published else None,
                    published_by=by if published else None,
                )
            )
        return aid

    async def save(self, agent_id: str, spec: dict[str, Any], *, by: str, note: str = "") -> int:
        """Saves `spec` as the next version, a draft. The published pointer does not move."""
        at = now_iso()
        async with self.engine.begin() as c:
            row = await self.row(agent_id, c)
            prev = (
                await c.execute(
                    sa.select(registry_agent_versions.c.spec).where(
                        registry_agent_versions.c.agent_id == agent_id,
                        registry_agent_versions.c.version == row["version"],
                    )
                )
            ).scalar_one()
            n = int(row["version"]) + 1
            await c.execute(
                registry_agent_versions.insert().values(
                    agent_id=agent_id,
                    version=n,
                    spec=spec,
                    digest=digest_of(spec),
                    note=note,
                    changes=changes_between(prev, spec),
                    saved_at=at,
                    saved_by=by,
                )
            )
            await c.execute(
                registry_agents.update()
                .where(registry_agents.c.id == agent_id)
                .values(version=n, owner=spec["owner"], updated_at=at)
            )
        return n

    async def publish(self, agent_id: str, version: int, *, by: str, review_id: str) -> None:
        at = now_iso()
        async with self.engine.begin() as c:
            await c.execute(
                registry_agent_versions.update()
                .where(registry_agent_versions.c.agent_id == agent_id, registry_agent_versions.c.version == version)
                .values(published_at=at, published_by=by, review_id=review_id)
            )
            await c.execute(
                registry_agents.update()
                .where(registry_agents.c.id == agent_id)
                .values(published_version=version, updated_at=at)
            )

    async def set_paused(self, agent_id: str, paused: bool) -> None:
        async with self.engine.begin() as c:
            await c.execute(
                registry_agents.update()
                .where(registry_agents.c.id == agent_id)
                .values(paused=paused, updated_at=now_iso())
            )

    async def delete(self, agent_id: str) -> None:
        async with self.engine.begin() as c:
            await self.row(agent_id, c)
            await c.execute(registry_agent_versions.delete().where(registry_agent_versions.c.agent_id == agent_id))
            await c.execute(
                publish_requests.delete().where(
                    publish_requests.c.kind == "agent", publish_requests.c.subject_id == agent_id
                )
            )
            await c.execute(registry_agents.delete().where(registry_agents.c.id == agent_id))

    async def open_request(
        self, kind: str, subject_id: str, version: int, *, note: str, by: str, body: dict[str, Any], approved: bool
    ) -> dict[str, Any]:
        """Records a publish request; 409 when one is already pending for the subject."""
        at = now_iso()
        prefix = "AGP" if kind == "agent" else "WFP"
        async with self.engine.begin() as c:
            pending = (
                await c.execute(
                    sa.select(publish_requests.c.id).where(
                        publish_requests.c.kind == kind,
                        publish_requests.c.subject_id == subject_id,
                        publish_requests.c.status == "pending",
                    )
                )
            ).first()
            if pending is not None:
                raise Conflict(f"Publish request {pending[0]} is already open.", code="review_open")
            count = (await c.execute(sa.select(sa.func.count()).select_from(publish_requests))).scalar_one()
            row = {
                "id": f"{prefix}-{1001 + int(count)}",
                "kind": kind,
                "subject_id": subject_id,
                "version": version,
                "status": "approved" if approved else "pending",
                "note": note,
                "requested_by": by,
                "created_at": at,
                "decided_at": at if approved else None,
                "decided_by": "auto-approve (dev)" if approved else None,
                "decision_reason": None,
                "body": body,
            }
            await c.execute(publish_requests.insert().values(**row))
        return row

    async def all_requests(self) -> list[dict[str, Any]]:
        q = sa.select(publish_requests).order_by(publish_requests.c.created_at.desc())
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def request(self, request_id: str) -> dict[str, Any]:
        q = sa.select(publish_requests).where(publish_requests.c.id == request_id)
        async with self.engine.connect() as c:
            r = (await c.execute(q)).mappings().first()
        if r is None:
            raise NotFound(f"Publish request {request_id}")
        return dict(r)

    async def decide_request(self, request_id: str, status: str, by: str, reason: str | None) -> bool:
        """Records the decision on a pending request; False when another decision got there first."""
        q = (
            publish_requests.update()
            .where(publish_requests.c.id == request_id, publish_requests.c.status == "pending")
            .values(status=status, decided_at=now_iso(), decided_by=by, decision_reason=reason)
        )
        async with self.engine.begin() as c:
            return (await c.execute(q)).rowcount == 1
