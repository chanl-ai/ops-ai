"""The agent registry's tables and queries: agents, their immutable versions, and publish requests shared with
workflows. `api/agent_registry.py` decides what is live and builds the console's views."""

from __future__ import annotations

import hashlib
import re
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.errors import Conflict, NotFound
from ops_service_kit.ids import canonical_json, new_id, now_iso
from ops_store import Guarantee
from ops_store.schema import TENANT_SCOPED

from .base import metadata
from .tenancy import LOCAL_TENANT, current_tenant, tenant_tx

registry_agents = sa.Table(
    "registry_agents",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("slug", sa.String(120), nullable=False, unique=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    # Newest saved version, draft or published.
    sa.Column("version", sa.Integer, nullable=False),
    # The version the runtime serves; null until the first publish.
    sa.Column("published_version", sa.Integer),
    sa.Column("paused", sa.Boolean, nullable=False, default=False),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False),
    # The template the provisioning service made it from, and how the platform protects it (c-180): `system` cannot be
    # changed by a person, `managed` can, and the template's fields come back on the next provisioning run.
    sa.Column("template_id", sa.String(120), index=True),
    sa.Column("protection", sa.String(16)),
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
    # Per tenant (c-333 phase A, migration 0067): a request id is unique within its tenant, and RLS shows a tenant only
    # its own. The records a request publishes (agents, guardrails, skills, widgets) are not per tenant yet (phase B).
    sa.Column("tenant_id", sa.String(64), primary_key=True, default=current_tenant, server_default=LOCAL_TENANT),
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
    # The primary key leads with tenant_id, so this adds nothing; it stays until a migration drops it.
    sa.Index("ix_registry_publish_requests_tenant_id", "tenant_id"),
    info=TENANT_SCOPED,
)
sa.Index("ix_registry_publish_requests_subject", publish_requests.c.kind, publish_requests.c.subject_id)
# A request id's prefix by kind; workflow kinds take WFP.
REQUEST_PREFIXES = {
    "agent": "AGP",
    "guardrail": "GRP",
    "skill": "SKP",
    "widget": "WDP",
    "deployment": "DPR",
    "tool_module": "TMP",
    "tool_access": "TAR",
}

SPEC_FIELDS = (
    "name",
    "role",
    "model",
    "channels",
    "instructions",
    "toolIds",
    "collections",
    "guardrails",
    "guardrailPins",
    "skillPins",
    "limits",
    "widgetPins",
    "widgets",
)


def digest_of(spec: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(spec).encode()).hexdigest()


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "agent"


def changes_between(old: dict[str, Any] | None, new: dict[str, Any]) -> list[str]:
    if old is None:
        return ["Created"]
    labels = {
        "toolIds": "tools",
        "collections": "knowledge bases",
        "guardrailPins": "guardrail pins",
        "skillPins": "skill pins",
        "limits": "caller limits",
        "widgetPins": "widgets",
        "widgets": "widget settings",
    }
    out = [f"Changed {labels.get(k, k)}" for k in SPEC_FIELDS if old.get(k) != new.get(k)]
    # A guardrail switched off or on names itself, so the review says what stopped (or started) being checked.
    pins: list[dict[str, Any]] = new.get("guardrailPins") or []
    held: list[dict[str, Any]] = old.get("guardrailPins") or []
    was = {p["guardrailId"]: p for p in held}
    for p in pins:
        before = was.get(p["guardrailId"])
        if before is not None and before.get("enabled", True) != p.get("enabled", True):
            state = "on" if p.get("enabled", True) else "off"
            out.append(f"Switched {p['name']} v{p['version']} {state}")
    return out or ["No changes"]


def _mine() -> sa.ColumnElement[bool]:
    """The current tenant's requests, named in every query as well as enforced by RLS (c-333): a database without RLS
    (SQL Server until c-349) still answers only for the tenant."""
    return publish_requests.c.tenant_id == current_tenant()


async def _name_tenant(c: AsyncConnection) -> None:
    if c.dialect.name == "postgresql":
        await c.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": current_tenant()})


class AgentRegistry:
    # A slug and a version number are unique keys (CAS); a save writes its version row and moves the agent in one
    # transaction, as does a publish (TRANSACTION). Only one publish request per subject may be pending (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def set_template(self, agent_id: str, *, template_id: str | None, protection: str | None) -> None:
        """Sets what the provisioning service owns on the row (c-180); a None leaves that column as it is."""
        values = {k: v for k, v in {"template_id": template_id, "protection": protection}.items() if v is not None}
        if values:
            async with self.engine.begin() as c:
                await c.execute(registry_agents.update().where(registry_agents.c.id == agent_id).values(**values))

    async def rows(self) -> list[dict[str, Any]]:
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(sa.select(registry_agents))).mappings()]

    async def row(self, agent_id: str, c: AsyncConnection | None = None, *, lock: bool = False) -> dict[str, Any]:
        q = sa.select(registry_agents).where(registry_agents.c.id == agent_id)
        if lock:
            q = q.with_for_update()
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

    async def published_spec(self, agent_id: str, version: int) -> dict[str, Any] | None:
        """A version's spec when it was published at some point, so a deployment pinned to it keeps serving it after a
        newer version goes live (c-117); None for a draft or an unknown version. Chat and widgets read pins here."""
        q = sa.select(registry_agent_versions.c.spec, registry_agent_versions.c.published_at).where(
            registry_agent_versions.c.agent_id == agent_id, registry_agent_versions.c.version == version
        )
        async with self.engine.connect() as c:
            r = (await c.execute(q)).first()
        return dict(r[0]) if r is not None and r[1] is not None else None

    async def requests(self, kind: str, subject_id: str) -> list[dict[str, Any]]:
        q = (
            sa.select(publish_requests)
            .where(_mine(), publish_requests.c.kind == kind, publish_requests.c.subject_id == subject_id)
            .order_by(publish_requests.c.created_at.desc())
        )
        async with tenant_tx(self.engine) as c:
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
        template_id: str | None = None,
        protection: str | None = None,
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
                    version=version,
                    published_version=version if published else None,
                    paused=False,
                    created_at=at,
                    updated_at=at,
                    template_id=template_id,
                    protection=protection,
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
        """Saves `spec` as the agent's one draft (c-172): it rewrites the newest version while that version is
        unpublished and no publish request has named it; otherwise it opens the next version as the draft, so neither
        what runs nor what a reviewer saw ever changes. The published pointer does not move."""
        at = now_iso()
        v = registry_agent_versions
        async with self.engine.begin() as c:
            # The publish-request check below reads a table under RLS: name the tenant for its policy in this
            # transaction, which runs as the owner because the agent tables are not per tenant yet (phase B, c-334).
            await _name_tenant(c)
            # Locked so two saves at once (two tabs, or autosave racing a slow save) take turns: unlocked, both read the
            # same newest version, both open the next one, and the second fails on the version key.
            row = await self.row(agent_id, c, lock=True)
            n = int(row["version"])
            newest = (await c.execute(sa.select(v).where(v.c.agent_id == agent_id, v.c.version == n))).mappings().one()
            asked = (
                await c.execute(
                    sa.select(publish_requests.c.id).where(
                        _mine(),
                        publish_requests.c.kind == "agent",
                        publish_requests.c.subject_id == agent_id,
                        publish_requests.c.version == n,
                    )
                )
            ).first()
            if newest["published_at"] is None and asked is None:
                # The draft keeps every change made to it, so its history entry reads as one change set.
                changes = list(dict.fromkeys([*newest["changes"], *changes_between(newest["spec"], spec)]))
                await c.execute(
                    v.update()
                    .where(v.c.agent_id == agent_id, v.c.version == n)
                    .values(
                        spec=spec,
                        digest=digest_of(spec),
                        note=note or newest["note"],
                        changes=changes,
                        saved_at=at,
                        saved_by=by,
                    )
                )
            else:
                n += 1
                await c.execute(
                    v.insert().values(
                        agent_id=agent_id,
                        version=n,
                        spec=spec,
                        digest=digest_of(spec),
                        note=note,
                        changes=changes_between(newest["spec"], spec),
                        saved_at=at,
                        saved_by=by,
                    )
                )
            await c.execute(
                registry_agents.update().where(registry_agents.c.id == agent_id).values(version=n, updated_at=at)
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
            await c.execute(registry_agents.delete().where(registry_agents.c.id == agent_id))
        # Requests are per tenant (RLS), the agent row not yet: the tenant's own requests go in their own transaction.
        async with tenant_tx(self.engine) as c:
            await c.execute(
                publish_requests.delete().where(
                    _mine(), publish_requests.c.kind == "agent", publish_requests.c.subject_id == agent_id
                )
            )

    async def open_request(
        self, kind: str, subject_id: str, version: int, *, note: str, by: str, body: dict[str, Any], approved: bool
    ) -> dict[str, Any]:
        """Records a publish request; 409 when one is already pending for the subject."""
        for attempt in range(3):
            try:
                return await self._open_request(
                    kind, subject_id, version, note=note, by=by, body=body, approved=approved
                )
            except IntegrityError:
                # Two opens in the tenant took the same number; the next attempt reads the one that landed.
                if attempt == 2:
                    raise
        raise AssertionError("unreachable")

    async def _open_request(
        self, kind: str, subject_id: str, version: int, *, note: str, by: str, body: dict[str, Any], approved: bool
    ) -> dict[str, Any]:
        at = now_iso()
        prefix = REQUEST_PREFIXES.get(kind, "WFP")
        async with tenant_tx(self.engine) as c:
            pending = (
                await c.execute(
                    sa.select(publish_requests.c.id).where(
                        _mine(),
                        publish_requests.c.kind == kind,
                        publish_requests.c.subject_id == subject_id,
                        publish_requests.c.status == "pending",
                    )
                )
            ).first()
            if pending is not None:
                raise Conflict(f"Publish request {pending[0]} is already open.", code="review_open")
            # The next number after the tenant's highest for this prefix. A row count repeats a number once a request
            # is deleted (an agent's are deleted with it).
            taken = (
                await c.execute(
                    sa.select(publish_requests.c.id).where(_mine(), publish_requests.c.id.like(f"{prefix}-%"))
                )
            ).scalars()
            numbers = [int(i.rsplit("-", 1)[1]) for i in taken if i.rsplit("-", 1)[1].isdigit()]
            row = {
                "id": f"{prefix}-{max(numbers, default=1000) + 1}",
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
        q = sa.select(publish_requests).where(_mine()).order_by(publish_requests.c.created_at.desc())
        async with tenant_tx(self.engine) as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def request(self, request_id: str) -> dict[str, Any]:
        q = sa.select(publish_requests).where(_mine(), publish_requests.c.id == request_id)
        async with tenant_tx(self.engine) as c:
            r = (await c.execute(q)).mappings().first()
        if r is None:
            raise NotFound(f"Publish request {request_id}")
        return dict(r)

    async def set_body(self, request_id: str, body: dict[str, Any]) -> None:
        async with tenant_tx(self.engine) as c:
            await c.execute(
                publish_requests.update().where(_mine(), publish_requests.c.id == request_id).values(body=body)
            )

    async def import_request(self, row: dict[str, Any]) -> bool:
        """Stores a request copied from another store under the id it was given; False when it is already here, so a
        copy can run again."""
        async with tenant_tx(self.engine) as c:
            if (
                await c.execute(sa.select(publish_requests.c.id).where(_mine(), publish_requests.c.id == row["id"]))
            ).first():
                return False
            await c.execute(publish_requests.insert().values(**row))
            return True

    async def decide_request(self, request_id: str, status: str, by: str, reason: str | None) -> bool:
        """Records the decision on a pending request; False when another decision got there first."""
        q = (
            publish_requests.update()
            .where(_mine(), publish_requests.c.id == request_id, publish_requests.c.status == "pending")
            .values(status=status, decided_at=now_iso(), decided_by=by, decision_reason=reason)
        )
        async with tenant_tx(self.engine) as c:
            return (await c.execute(q)).rowcount == 1
