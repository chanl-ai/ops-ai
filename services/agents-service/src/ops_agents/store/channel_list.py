"""The Channels list (c-245): each door people reach an agent or workflow through, from the record that already holds
it, under that record's id. A mailbox (`mbx_`) is an email channel and serves the live workflows whose Email received
trigger names its address; a widget deployment (`wd_`) is a chat channel and serves its agent, pinned or on the latest
published version; an API key (`key_`, platform-service's record) is an API channel and serves its target. Traffic,
errors and the last read are counted here in a few grouped queries for the whole list."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, cast

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_engine.store.tables import engine_definitions, engine_runs
from ops_store import Guarantee
from ops_store.team_scope import team_visible

from .agent_registry import registry_agent_versions, registry_agents
from .graphs import graph_threads
from .mailboxes import mailboxes
from .poll_cursors import poll_cursors
from .tenancy import current_tenant, tenant_tx
from .trigger_events import trigger_events
from .widget_deployments import widget_deployments

EMAIL_TRIGGER = "ops.trigger.email"
# An agent the registry does not hold, as distinct from one with no published version (None).
NOT_FOUND: Any = object()
# A mailbox not read for this long is amber: the listener polls every few seconds and IDLE wakes it at once.
STALE_READ = timedelta(minutes=5)


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _in(column: sa.ColumnElement[Any], teams: tuple[str, ...] | None) -> sa.ColumnElement[bool]:
    return sa.true() if teams is None else column.in_(teams)


@dataclass
class Counts:
    traffic24h: int = 0
    errors24h: int = 0
    activity7d: int = 0
    last_activity_at: str | None = None


@dataclass
class Listed:
    email: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    chat: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])


def watched_address(definition: dict[str, Any] | None) -> str | None:
    """The mailbox a definition's Email received trigger names, if it has one."""
    nodes = cast(list[dict[str, Any]], (definition or {}).get("nodes") or [])
    for node in nodes:
        if node.get("type") == EMAIL_TRIGGER:
            params = cast(dict[str, Any], node.get("parameters") or {})
            return str(params.get("mailbox") or "") or None
    return None


class ChannelList:
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def live_definitions(self) -> list[dict[str, Any]]:
        """The tenant's live workflow versions, with their definitions."""
        d = engine_definitions
        q = sa.select(d.c.workflow_id, d.c.name, d.c.version, d.c.definition, d.c.team_id).where(
            d.c.tenant_id == current_tenant(), d.c.stage == "live", d.c.archived_at.is_(None)
        )
        async with tenant_tx(self.engine) as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def published_version(self, agent_id: str) -> Any:
        """The agent's published version, None when it has none, NOT_FOUND when there is no such agent. The registry is
        not a tenant table, so it is read on its own connection."""
        a = registry_agents
        async with self.engine.connect() as c:
            row = (await c.execute(sa.select(a.c.published_version).where(a.c.id == agent_id, team_visible(a)))).first()
        return NOT_FOUND if row is None else row[0]

    async def api_rows(self, keys: list[dict[str, Any]], *, now: datetime | None = None) -> list[dict[str, Any]]:
        """API keys (platform-service's records, c-246) with their traffic and what they serve: runs and threads a key
        started record `key:<id>`, and a key's target is named from the live workflow or the agent's registry row."""
        if not keys:
            return []
        at = now or datetime.now(UTC)
        day, week = _iso(at - timedelta(days=1)), _iso(at - timedelta(days=7))
        tenant = current_tenant()
        starters = [f"key:{k['id']}" for k in keys]
        counts: dict[str, Counts] = {s: Counts() for s in starters}
        r, t, d = engine_runs, graph_threads, engine_definitions
        thread_starter = t.c.meta["startedBy"].as_string()
        async with tenant_tx(self.engine) as c:
            for who, n_day, n_err, n_week, last in (
                await c.execute(
                    sa.select(
                        r.c.created_by,
                        sa.func.count().filter(r.c.created_at >= day),
                        sa.func.count().filter(sa.and_(r.c.created_at >= day, r.c.status == "failed")),
                        sa.func.count().filter(r.c.created_at >= week),
                        sa.func.max(r.c.created_at),
                    )
                    .where(r.c.tenant_id == tenant, r.c.created_by.in_(starters))
                    .group_by(r.c.created_by)
                )
            ).all():
                counts[str(who)] = Counts(int(n_day), int(n_err), int(n_week), last)
            for who, n_day, n_err, n_week, last in (
                await c.execute(
                    sa.select(
                        thread_starter,
                        sa.func.count().filter(t.c.created_at >= day),
                        sa.func.count().filter(sa.and_(t.c.created_at >= day, t.c.status == "error")),
                        sa.func.count().filter(t.c.created_at >= week),
                        sa.func.max(t.c.updated_at),
                    )
                    .where(t.c.tenant_id == tenant, thread_starter.in_(starters))
                    .group_by(thread_starter)
                )
            ).all():
                was = counts[str(who)]
                counts[str(who)] = Counts(
                    was.traffic24h + int(n_day),
                    was.errors24h + int(n_err),
                    was.activity7d + int(n_week),
                    max(filter(None, (was.last_activity_at, last)), default=None),
                )
            workflows = {
                str(w): (str(n or w), v)
                for w, n, v in (
                    await c.execute(
                        sa.select(d.c.workflow_id, d.c.name, d.c.version).where(
                            d.c.tenant_id == tenant, d.c.stage == "live"
                        )
                    )
                ).all()
            }
        agent_ids = {str(k["target"]["id"]) for k in keys if k.get("target") and k["target"]["kind"] == "agent"}
        agents: dict[str, tuple[str, Any]] = {}
        if agent_ids:
            a, v = registry_agents, registry_agent_versions
            q = (
                sa.select(a.c.id, v.c.spec["name"].as_string(), a.c.published_version)
                .select_from(a.join(v, sa.and_(v.c.agent_id == a.c.id, v.c.version == a.c.version)))
                .where(a.c.id.in_(agent_ids))
            )
            async with self.engine.connect() as c:
                agents = {str(i): (str(n or i), pv) for i, n, pv in (await c.execute(q)).all()}
        out: list[dict[str, Any]] = []
        for k in keys:
            target = k.get("target")
            named = None
            if target:
                found = (workflows if target["kind"] == "workflow" else agents).get(str(target["id"]))
                named = found or (str(target["id"]), None)
            out.append(
                k
                | {
                    "counts": counts[f"key:{k['id']}"],
                    "serves_name": named[0] if named else None,
                    "latest_version": named[1] if named else None,
                }
            )
        return out

    async def rows(
        self, teams: tuple[str, ...] | None, *, now: datetime | None = None, retired: bool = False
    ) -> Listed:
        """`retired` keeps retired chat channels in the list, for an agent's embed table; Channels leaves them out."""
        at = now or datetime.now(UTC)
        day, week = _iso(at - timedelta(days=1)), _iso(at - timedelta(days=7))
        tenant = current_tenant()
        out = Listed()
        async with tenant_tx(self.engine) as c:
            m = mailboxes
            boxes = [
                dict(r)
                for r in (
                    await c.execute(
                        m.select().where(m.c.tenant_id == tenant, _in(m.c.team_id, teams)).order_by(m.c.name)
                    )
                ).mappings()
            ]
            d = engine_definitions
            live = [
                dict(r)
                for r in (
                    await c.execute(
                        sa.select(d.c.workflow_id, d.c.name, d.c.version, d.c.definition, d.c.team_id).where(
                            d.c.tenant_id == tenant, d.c.stage == "live"
                        )
                    )
                ).mappings()
            ]
            watching: dict[str, list[dict[str, Any]]] = {}
            for row in live:
                if address := watched_address(row["definition"]):
                    watching.setdefault(address, []).append(row)
            cursors = poll_cursors
            read_at = {
                str(r.binding_id): str(r.updated_at)
                for r in await c.execute(
                    sa.select(cursors.c.binding_id, cursors.c.updated_at).where(cursors.c.tenant_id == tenant)
                )
            }
            e = trigger_events
            mail_counts: dict[str, Counts] = {}
            q = (
                sa.select(
                    e.c.source,
                    sa.func.count().filter(e.c.recorded_at >= day),
                    sa.func.count().filter(e.c.recorded_at >= week),
                    sa.func.max(e.c.recorded_at),
                )
                .where(e.c.tenant_id == tenant)
                .group_by(e.c.source)
            )
            for source, n_day, n_week, last in (await c.execute(q)).all():
                mail_counts[str(source)] = Counts(int(n_day), 0, int(n_week), last)
            r = engine_runs
            q = (
                sa.select(r.c.created_by, sa.func.count())
                .where(
                    r.c.tenant_id == tenant,
                    r.c.created_by.like("trigger:email:%"),
                    r.c.status == "failed",
                    r.c.created_at >= day,
                )
                .group_by(r.c.created_by)
            )
            for who, n in (await c.execute(q)).all():
                mail_counts.setdefault("email:" + str(who)[len("trigger:email:") :], Counts()).errors24h = int(n)
            for box in boxes:
                # A workflow reads a mailbox of its own team only (email_trigger.bindable).
                serving = [x for x in watching.get(str(box["address"]), []) if x["team_id"] == box["team_id"]]
                reads = [
                    read_at[f"email:{w['workflow_id']}"] for w in serving if f"email:{w['workflow_id']}" in read_at
                ]
                out.email.append(
                    box
                    | {
                        "serving": serving,
                        "last_read_at": max(reads) if reads else None,
                        "counts": mail_counts.get(f"email:{box['address']}", Counts()),
                    }
                )

            w = widget_deployments
            deployments = [
                dict(row)
                for row in (
                    await c.execute(
                        w.select()
                        .where(
                            w.c.tenant_id == tenant,
                            sa.true() if retired else w.c.retired_at.is_(None),
                            _in(w.c.team_id, teams),
                        )
                        .order_by(w.c.name)
                    )
                ).mappings()
            ]
            t = graph_threads
            chat_counts: dict[str, Counts] = {}
            q = (
                sa.select(
                    t.c.deployment_id,
                    sa.func.count().filter(t.c.created_at >= day),
                    sa.func.count().filter(sa.and_(t.c.created_at >= day, t.c.status == "error")),
                    sa.func.count().filter(t.c.created_at >= week),
                    sa.func.max(t.c.updated_at),
                )
                .where(t.c.tenant_id == tenant, t.c.deployment_id.is_not(None), team_visible(t))
                .group_by(t.c.deployment_id)
            )
            for dep_id, n_day, n_err, n_week, last in (await c.execute(q)).all():
                chat_counts[str(dep_id)] = Counts(int(n_day), int(n_err), int(n_week), last)
            for dep in deployments:
                out.chat.append(
                    dep
                    | {
                        "agent_name": str(dep["agent_id"]),
                        "published_version": None,
                        "counts": chat_counts.get(str(dep["id"]), Counts()),
                    }
                )
        agent_ids = {str(dep["agent_id"]) for dep in out.chat}
        if agent_ids:
            # The registry is not a tenant table: the tenant role cannot read it, so it is read on its own connection.
            a, v = registry_agents, registry_agent_versions
            q = (
                sa.select(a.c.id, v.c.spec["name"].as_string(), a.c.published_version)
                .select_from(a.join(v, sa.and_(v.c.agent_id == a.c.id, v.c.version == a.c.version)))
                .where(a.c.id.in_(agent_ids))
            )
            async with self.engine.connect() as c:
                agents = {str(i): (str(n or i), p) for i, n, p in (await c.execute(q)).all()}
            for dep in out.chat:
                dep["agent_name"], dep["published_version"] = agents.get(
                    str(dep["agent_id"]), (str(dep["agent_id"]), None)
                )
        return out
