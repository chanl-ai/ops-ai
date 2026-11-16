"""The agent registry's tables and queries: agents, their immutable versions, and publish requests shared with
workflows. `api/agent_registry.py` decides what is live and builds the console's views."""

from __future__ import annotations

import hashlib
import re
from typing import Any, ClassVar

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_service_kit.errors import Conflict, NotFound
from ops_service_kit.ids import canonical_json, new_id, now_iso
from ops_service_kit.listing import ListParams
from ops_store import Guarantee, isolation
from ops_store.dialect import json_text
from ops_store.listing import LISTED, ListPage, list_page
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, team_owned_via
from ops_store.team_scope import any_team, team_visible

from .base import metadata
from .graphs import graph_threads, mine
from .tenancy import OWNER, SERVE_PUBLISHED, UNIQUE_KEY, RuntimeStore, current_tenant

registry_agents = sa.Table(
    "registry_agents",
    metadata,
    # The tenant the row belongs to, the caller's on insert, with no default (agents 0109).
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("slug", sa.String(120), nullable=False),
    sa.Column("team_id", sa.String(64), nullable=False, info=LISTED),
    # Newest saved version, draft or published.
    sa.Column("version", sa.Integer, nullable=False, info=LISTED),
    # The version the runtime serves; null until the first publish.
    sa.Column("published_version", sa.Integer),
    sa.Column("paused", sa.Boolean, nullable=False, default=False),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False, info=LISTED),
    # The template the provisioning service made it from, and how the platform protects it: `system` cannot be
    # changed by a person, `managed` can, and the template's fields come back on the next provisioning run.
    sa.Column("template_id", sa.String(120), index=True, info=LISTED),
    sa.Column("protection", sa.String(16)),
    # A slug is unique within its tenant only.
    sa.UniqueConstraint("tenant_id", "slug", name="uq_registry_agents_tenant_slug"),
    # The agents list, one team's page by update time or version.
    sa.Index("ix_registry_agents_team_updated", "tenant_id", "team_id", "updated_at"),
    sa.Index("ix_registry_agents_team_version", "tenant_id", "team_id", "version"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

registry_agent_versions = sa.Table(
    "registry_agent_versions",
    metadata,
    # The tenant the row belongs to, the caller's on insert, with no default (agents 0109).
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant),
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
    info={**TENANT_SCOPED, **team_owned_via("registry_agents", "agent_id")},
)

publish_requests = sa.Table(
    "registry_publish_requests",
    metadata,
    # Per tenant (migration 0067): a request id is unique within its tenant, and RLS shows a tenant only
    # its own. The records a request publishes (agents, guardrails, skills, widgets) are not per tenant yet (phase B).
    sa.Column("tenant_id", sa.String(64), primary_key=True, default=current_tenant),
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
    # The team of the agent or workflow the request publishes (agents 0106); empty until the stores write it.
    sa.Column("team_id", sa.String(64), nullable=False, server_default=""),
    sa.Index("ix_registry_publish_requests_team", "tenant_id", "team_id"),
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
    "egress_host": "EGH",
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


# (agent, version) pairs per statement of published_specs: two parameters each, under SQL Server's 2100.
PAIRS_PER_QUERY = 500
# A JSON boolean as text: 'true' on PostgreSQL and SQL Server, '1' on SQLite.
_TRUE = ("true", "1")


def _word(word: str) -> sa.ColumnClause[str]:
    """A fixed word written into the statement, not bound: a GROUP BY must name the same expression the select does,
    and two bound copies of one value are two parameters to SQL Server."""
    return sa.literal_column(f"'{word}'", sa.String())


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
    """The current tenant's requests, named in every query as well as enforced by RLS: a database without RLS
    (SQL Server, for now) still answers only for the tenant."""
    return publish_requests.c.tenant_id == current_tenant()


async def _name_tenant(c: AsyncConnection) -> None:
    if c.dialect.name == "postgresql":
        await c.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": current_tenant()})


async def publish_requested(c: AsyncConnection, kind: str, subject_id: str, version: int) -> bool:
    """Whether a publish request names this version, decided or not. A saver that finds one opens the next version
    instead of rewriting the draft a reviewer saw. The request table is read under RLS, so the tenant is named for
    its policy in this transaction (the registry tables are not per tenant yet, phase B)."""
    await _name_tenant(c)
    q = sa.select(publish_requests.c.id).where(
        _mine(),
        publish_requests.c.kind == kind,
        publish_requests.c.subject_id == subject_id,
        publish_requests.c.version == version,
    )
    return (await c.execute(q)).first() is not None


class AgentRegistry(RuntimeStore):
    # A slug and a version number are unique keys (CAS); a save writes its version row and moves the agent in one
    # transaction, as does a publish (TRANSACTION). Only one publish request per subject may be pending (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})

    async def set_template(self, agent_id: str, *, template_id: str | None, protection: str | None) -> None:
        """Sets what the provisioning service owns on the row; a None leaves that column as it is."""
        values = {k: v for k, v in {"template_id": template_id, "protection": protection}.items() if v is not None}
        if values:
            async with self.tx() as c:
                await c.execute(registry_agents.update().where(registry_agents.c.id == agent_id).values(**values))

    async def rows(self) -> list[dict[str, Any]]:
        """The acting team's agents of the caller's tenant (every team's with no acting team: a loop or the seed)."""
        q = sa.select(registry_agents).where(
            registry_agents.c.tenant_id == current_tenant(), team_visible(registry_agents)
        )
        async with self.tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def published_pointers(self) -> list[tuple[str, str, int | None, bool]]:
        """Every tenant's agents as (tenant, id, published version, paused), read past the tenant at start: the system
        role is granted these four columns of the table only (agents 0107), never a spec."""
        a = registry_agents
        q = sa.select(a.c.tenant_id, a.c.id, a.c.published_version, a.c.paused).where(
            any_team(a, "the start-up serves every team's published agents")
        )
        async with self.system_tx(SERVE_PUBLISHED) as c:
            rows = (await c.execute(q)).all()
        return [(str(t), str(i), None if v is None else int(v), bool(p)) for t, i, v, p in rows]

    async def published_specs(self, keys: set[tuple[str, int]]) -> dict[tuple[str, int], dict[str, JsonValue]]:
        """The spec of each (agent, version) of `keys` in the caller's tenant, in queries of at most PAIRS_PER_QUERY
        pairs (SQL Server takes at most 2100 parameters a statement)."""
        v = registry_agent_versions
        ordered = sorted(keys)
        out: dict[tuple[str, int], dict[str, JsonValue]] = {}
        async with self.tx() as c:
            for i in range(0, len(ordered), PAIRS_PER_QUERY):
                chunk = ordered[i : i + PAIRS_PER_QUERY]
                pairs = sa.or_(*(sa.and_(v.c.agent_id == agent, v.c.version == n) for agent, n in chunk))
                q = sa.select(v.c.agent_id, v.c.version, v.c.spec).where(
                    v.c.tenant_id == current_tenant(), pairs, team_visible(v)
                )
                for agent, n, spec in (await c.execute(q)).all():
                    out[(str(agent), int(n))] = dict(spec)
        return out

    async def owner_team(self, agent_id: str, conn: AsyncConnection | None = None) -> str | None:
        """The team that owns an agent, whoever is acting; None when there is no such agent. Only for deciding a
        refusal by the owning team, never for showing the agent."""
        return (await self.owner_teams(conn, registry_agents, {agent_id}, OWNER)).get(agent_id)

    async def tenant_owners(self, ids: set[str]) -> dict[str, str]:
        """Of `ids`, the agents the caller's tenant holds, each with its owning team ('' for none), whoever is acting.
        The serving catalogue holds every tenant's agents by id, so a route asks this before it serves one from it;
        only for deciding a refusal, never for showing the agent."""
        if not ids:
            return {}
        q = sa.select(registry_agents.c.id, registry_agents.c.team_id).where(
            registry_agents.c.tenant_id == current_tenant(),
            registry_agents.c.id.in_(sorted(ids)),
            any_team(registry_agents, OWNER),
        )
        with isolation.tenant_wide(OWNER):
            async with self.tx() as c:
                return {str(i): str(team or "") for i, team in (await c.execute(q)).all()}

    async def row(self, agent_id: str, c: AsyncConnection | None = None, *, lock: bool = False) -> dict[str, Any]:
        """The agent, when the acting team owns it; another team's agent is NotFound, so its routes answer 404."""
        q = sa.select(registry_agents).where(
            mine(registry_agents), registry_agents.c.id == agent_id, team_visible(registry_agents)
        )
        if lock:
            q = q.with_for_update()
        if c is None:
            async with self.tx() as conn:
                r = (await conn.execute(q)).mappings().first()
        else:
            r = (await c.execute(q)).mappings().first()
        if r is None:
            raise NotFound(f"Agent {agent_id}")
        return dict(r)

    async def page(self, params: ListParams, *, since: str) -> ListPage:
        """One page of the acting team's agents, each row with its newest version's spec and `tasks_24h`, the threads
        started on it since `since` (chats naming it and threads on its own graph, a builder's test left out). Sorted
        by name, then the key; `search` matches name, role and slug; `availability`, `teamId` and `templateId` filter,
        and the first two are counted."""
        a, v, t = registry_agents, registry_agent_versions, graph_threads
        name, role = json_text(v.c.spec, "name"), json_text(v.c.spec, "role")
        tasks = (
            sa.select(sa.func.count())
            .select_from(t)
            .where(
                mine(t),
                team_visible(t),
                t.c.created_at >= since,
                sa.or_(
                    t.c.graph == sa.literal("agent:") + a.c.id,
                    sa.and_(t.c.graph == "agent_wrapper", json_text(t.c.meta, "agentId") == a.c.id),
                ),
                sa.func.coalesce(json_text(t.c.meta, "test"), "false").not_in(_TRUE),
            )
            .scalar_subquery()
        )
        availability = sa.case(
            (a.c.paused == sa.true(), _word("paused")),
            (a.c.published_version.is_not(None), _word("published")),
            else_=_word("not_published"),
        )
        q = (
            sa.select(a, v.c.spec, tasks.label("tasks_24h"))
            .join(v, sa.and_(v.c.tenant_id == a.c.tenant_id, v.c.agent_id == a.c.id, v.c.version == a.c.version))
            .where(a.c.tenant_id == current_tenant(), team_visible(a), team_visible(v))
        )
        async with self.tx() as c:
            return await list_page(
                c,
                q,
                params,
                search=[name, role, a.c.slug],
                sortable={
                    "name": name,
                    "updatedAt": a.c.updated_at,
                    "tasks24h": tasks,
                    "version": a.c.version,
                    "teamId": a.c.team_id,
                    "availability": availability,
                },
                default_sort=name.asc(),
                filters={"availability": availability, "teamId": a.c.team_id, "templateId": a.c.template_id},
                facets={"availability": availability, "teamId": a.c.team_id},
            )

    async def versions(self, agent_id: str) -> list[dict[str, Any]]:
        q = (
            sa.select(registry_agent_versions)
            .where(
                mine(registry_agent_versions),
                registry_agent_versions.c.agent_id == agent_id,
                team_visible(registry_agent_versions),
            )
            .order_by(registry_agent_versions.c.version.desc())
        )
        async with self.tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def version(self, agent_id: str, version: int) -> dict[str, Any]:
        q = sa.select(registry_agent_versions).where(
            mine(registry_agent_versions),
            registry_agent_versions.c.agent_id == agent_id,
            registry_agent_versions.c.version == version,
            team_visible(registry_agent_versions),
        )
        async with self.tx() as c:
            r = (await c.execute(q)).mappings().first()
        if r is None:
            raise NotFound(f"Agent {agent_id} version {version}")
        return dict(r)

    async def named_versions(self, keys: set[tuple[str, int]]) -> dict[tuple[str, int], tuple[str, str]]:
        """Each (agent, version) of `keys` the acting team sees, as that version's name and the agent's slug, in one
        query; a key the team does not see is left out. A list of publish requests reads its agents this way."""
        if not keys:
            return {}
        v, a = registry_agent_versions, registry_agents
        pairs = sa.or_(*(sa.and_(v.c.agent_id == agent, v.c.version == n) for agent, n in sorted(keys)))
        q = (
            sa.select(v.c.agent_id, v.c.version, v.c.spec, a.c.slug)
            .join(a, a.c.id == v.c.agent_id)
            .where(pairs, team_visible(a), team_visible(v))
        )
        async with self.tx() as c:
            rows = (await c.execute(q)).mappings().all()
        return {(str(r["agent_id"]), int(r["version"])): (str(r["spec"]["name"]), str(r["slug"])) for r in rows}

    async def published_spec(self, agent_id: str, version: int) -> dict[str, Any] | None:
        """A version's spec when it was published at some point, so a deployment pinned to it keeps serving it after a
        newer version goes live; None for a draft or an unknown version. Chat and widgets read pins here."""
        q = sa.select(registry_agent_versions.c.spec, registry_agent_versions.c.published_at).where(
            registry_agent_versions.c.agent_id == agent_id,
            registry_agent_versions.c.version == version,
            team_visible(registry_agent_versions),
        )
        async with self.tx() as c:
            r = (await c.execute(q)).first()
        return dict(r[0]) if r is not None and r[1] is not None else None

    async def requests(self, kind: str, subject_id: str) -> list[dict[str, Any]]:
        q = (
            sa.select(publish_requests)
            .where(_mine(), publish_requests.c.kind == kind, publish_requests.c.subject_id == subject_id)
            .order_by(publish_requests.c.created_at.desc())
        )
        async with self.tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def _unique_slug(self, c: AsyncConnection, name: str) -> str:
        base = slugify(name)
        q = sa.select(registry_agents.c.slug).where(
            mine(registry_agents),
            registry_agents.c.slug.like(f"{base}%"),
            any_team(registry_agents, "a slug is unique across every team"),
        )
        # The team policy shows a team only its own rows; the slug is unique across the tenant's teams.
        async with isolation.tenant_wide_on(c, UNIQUE_KEY) as wide:
            taken = {str(s) for s in (await wide.execute(q)).scalars()}
        n, slug = 2, base
        while slug in taken:
            slug, n = f"{base}-{n}", n + 1
        return slug

    async def create_if_absent(self, spec: dict[str, Any], *, by: str, team_id: str, agent_id: str) -> bool:
        """`create` for an agent whose id is fixed (a team's Ops Assistant): False when a row of that id, or one
        racing it for the same slug, is already there, so two first chats at once leave one agent."""
        try:
            async with self.tx() as c, self.attempt(c):
                await self.create(spec, by=by, team_id=team_id, agent_id=agent_id, published=True, conn=c)
        except IntegrityError:
            return False
        return True

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
        conn: AsyncConnection | None = None,
    ) -> str:
        if conn is None:
            async with self.tx() as c:
                return await self.create(
                    spec,
                    by=by,
                    team_id=team_id,
                    agent_id=agent_id,
                    version=version,
                    published=published,
                    template_id=template_id,
                    protection=protection,
                    conn=c,
                )
        c = conn
        aid = agent_id or new_id("ag")
        at = now_iso()
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
        """Saves `spec` as the agent's one draft: it rewrites the newest version while that version is
        unpublished and no publish request has named it; otherwise it opens the next version as the draft, so neither
        what runs nor what a reviewer saw ever changes. The published pointer does not move."""
        at = now_iso()
        v = registry_agent_versions
        async with self.tx() as c:
            # Locked so two saves at once (two tabs, or autosave racing a slow save) take turns: unlocked, both read the
            # same newest version, both open the next one, and the second fails on the version key.
            row = await self.row(agent_id, c, lock=True)
            n = int(row["version"])
            newest = (
                (await c.execute(sa.select(v).where(v.c.agent_id == agent_id, v.c.version == n, team_visible(v))))
                .mappings()
                .one()
            )
            asked = await publish_requested(c, "agent", agent_id, n)
            if newest["published_at"] is None and not asked:
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
        async with self.tx() as c:
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
        async with self.tx() as c:
            await c.execute(
                registry_agents.update()
                .where(registry_agents.c.id == agent_id)
                .values(paused=paused, updated_at=now_iso())
            )

    async def delete(self, agent_id: str) -> None:
        async with self.tx() as c:
            await self.row(agent_id, c)
            await c.execute(registry_agent_versions.delete().where(registry_agent_versions.c.agent_id == agent_id))
            await c.execute(registry_agents.delete().where(registry_agents.c.id == agent_id))
            await c.execute(
                publish_requests.delete().where(
                    _mine(), publish_requests.c.kind == "agent", publish_requests.c.subject_id == agent_id
                )
            )

    async def open_request(
        self,
        kind: str,
        subject_id: str,
        version: int,
        *,
        note: str,
        by: str,
        body: dict[str, Any],
        approved: bool,
        replaces_older: bool = False,
    ) -> dict[str, Any]:
        """Records a publish request; 409 when one is already pending for the subject. With `replaces_older`, a pending
        request for an older version is returned to its author instead: only the newest draft may publish, so
        the older one could only ever put a version live that lacks what was saved since."""
        for attempt in range(3):
            try:
                async with self.tx() as c, self.attempt(c):
                    return await self._open_request(
                        c,
                        kind,
                        subject_id,
                        version,
                        note=note,
                        by=by,
                        body=body,
                        approved=approved,
                        replaces_older=replaces_older,
                    )
            except IntegrityError:
                # Two opens in the tenant took the same number; the next attempt reads the one that landed.
                if attempt == 2:
                    raise
        raise AssertionError("unreachable")

    async def _open_request(
        self,
        c: AsyncConnection,
        kind: str,
        subject_id: str,
        version: int,
        *,
        note: str,
        by: str,
        body: dict[str, Any],
        approved: bool,
        replaces_older: bool,
    ) -> dict[str, Any]:
        at = now_iso()
        prefix = REQUEST_PREFIXES.get(kind, "WFP")
        pending = (
            await c.execute(
                sa.select(publish_requests.c.id, publish_requests.c.version).where(
                    _mine(),
                    publish_requests.c.kind == kind,
                    publish_requests.c.subject_id == subject_id,
                    publish_requests.c.status == "pending",
                )
            )
        ).first()
        if pending is not None and not (replaces_older and int(pending[1]) < version):
            raise Conflict(f"Publish request {pending[0]} is already open.", code="review_open")
        if pending is not None:
            # Returned, the state a reviewer's send-back leaves, so a late approval of it answers already_decided.
            await c.execute(
                publish_requests.update()
                .where(_mine(), publish_requests.c.id == pending[0], publish_requests.c.status == "pending")
                .values(
                    status="returned",
                    decided_at=at,
                    decided_by=by,
                    decision_reason=f"Replaced by the request for version {version}.",
                )
            )
        # The next number after the tenant's highest for this prefix. A row count repeats a number once a request
        # is deleted (an agent's are deleted with it).
        taken = (
            await c.execute(sa.select(publish_requests.c.id).where(_mine(), publish_requests.c.id.like(f"{prefix}-%")))
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
        async with self.tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def request(self, request_id: str) -> dict[str, Any]:
        q = sa.select(publish_requests).where(_mine(), publish_requests.c.id == request_id)
        async with self.tx() as c:
            r = (await c.execute(q)).mappings().first()
        if r is None:
            raise NotFound(f"Publish request {request_id}")
        return dict(r)

    async def set_body(self, request_id: str, body: dict[str, Any]) -> None:
        async with self.tx() as c:
            await c.execute(
                publish_requests.update().where(_mine(), publish_requests.c.id == request_id).values(body=body)
            )

    async def import_request(self, row: dict[str, Any]) -> bool:
        """Stores a request copied from another store under the id it was given; False when it is already here, so a
        copy can run again."""
        async with self.tx() as c:
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
        async with self.tx() as c:
            return (await c.execute(q)).rowcount == 1
