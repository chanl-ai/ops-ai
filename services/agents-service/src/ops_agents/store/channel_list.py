"""The Channels list: each door people reach an agent or workflow through, from the record that already holds
it, under that record's id. A mailbox (`mbx_`) is an email channel and serves the live workflows whose Email received
trigger names its address (engine_definitions.mailbox); a widget deployment (`wd_`) is a chat channel and serves its
agent, pinned or on the latest published version; an API key (`key_`, the copy of platform-service's record in
api_key_copies) is an API channel and serves its target.

The three are one UNION ALL (`channels`), so the list searches, filters, counts its facets and pages in SQL; each row's
health state is a CASE over its own columns at the request's time. Traffic, errors, the last read and what a row
serves are then read for the page's rows only, in a few grouped queries, so the statements stay the same however
many channels there are."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, cast

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_engine.store.definitions import watched_mailbox
from ops_engine.store.tables import engine_definitions, engine_runs
from ops_service_kit.http import JsonValue, Out
from ops_service_kit.listing import ListParams
from ops_store import Guarantee, copies
from ops_store.listing import ListPage, list_page
from ops_store.rows import rows
from ops_store.team_scope import any_team, team_visible

from .agent_registry import registry_agent_versions, registry_agents
from .api_key_copies import api_key_copies
from .graphs import graph_threads
from .mailboxes import mailboxes
from .poll_cursors import poll_cursors
from .tenancy import RuntimeStore, current_tenant
from .trigger_events import trigger_events
from .widget_deployments import widget_deployments
from .widget_keys import widget_mint_keys

# An agent the registry does not hold, as distinct from one with no published version (None).
NOT_FOUND: Any = object()
# A mailbox not read for this long is amber: the listener polls every few seconds and IDLE wakes it at once.
STALE_READ = timedelta(minutes=5)
# A key expiring sooner than this is amber, so someone rotates it before the systems calling it start failing.
KEY_EXPIRY_WARNING = timedelta(days=14)
# The list names the teams the caller asked for and may view channels of, which with `team=all` are several.
ASKED_TEAMS = "the Channels list names each team the caller asked for and may view (team=all is several)"
# The list's order: email, then chat, then API, each by name, then the type and id.
RANK = {"email": "0", "chat": "1", "api": "2"}
WORST = {"error": 3, "warn": 2, "ok": 1, "idle": 0}


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class Counts:
    traffic24h: int = 0
    errors24h: int = 0
    activity7d: int = 0
    last_activity_at: str | None = None


@dataclass(frozen=True)
class KindCount:
    """One channel type over the caller's whole list, retired embeds left out."""

    type: str
    total: int
    active: int
    attention: int
    worst: str | None


class ChannelRecord(BaseModel):
    """One row of the union (`channels`), then its details for the page (`_details`)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    type: str
    id: str
    name: str
    # The address, the key's prefix, or (searched) an embed's allowed websites as JSON text.
    detail: str
    team_id: str
    paused: int
    health: str
    retired_at: str | None
    serves_kind: str | None
    serves_id: str | None
    pinned: int | None
    serves_count: int
    read_at: str | None
    expires_at: str | None
    key_status: str | None
    counts: Counts = Field(default_factory=Counts)
    # Chat rows: the allowed websites and unrevoked mint keys.
    origins: list[str] = Field(default_factory=list[str])
    active_keys: int = 0
    serves_name: str | None = None
    latest_version: int | None = None


@dataclass
class Listed:
    # The pagination and facets; its rows are `rows`.
    page: ListPage
    rows: list[ChannelRecord]
    kinds: list[KindCount] = field(default_factory=list[KindCount])


def watched_address(definition: JsonValue) -> str | None:
    """The mailbox a definition's Email received trigger names, if it has one."""
    return watched_mailbox(definition or {})


class LiveDefinition(Out):
    """One live workflow version. The definition stays the JSON it was stored as, so a reader that fails on an odd one
    fails where it did."""

    workflow_id: str
    name: str
    version: int
    definition: JsonValue
    team_id: str | None


def _int(column: sa.ColumnElement[Any]) -> sa.ColumnElement[int]:
    return sa.cast(column, sa.Integer)


def _text(value: str | None = None) -> sa.ColumnElement[str]:
    return sa.cast(sa.literal(value) if value is not None else sa.null(), sa.String(320))


def channels(teams: Sequence[str], *, now: datetime, retired: bool = False, agent_id: str | None = None) -> sa.Subquery:
    """Every channel of `teams` in the current tenant, one row each, with its health state at `now`. Each branch names
    its tenant and teams itself; the row policies hold it to them as well."""
    tenant = current_tenant()
    stale = _iso(now - STALE_READ)
    now_at, warn_at = _iso(now), _iso(now + KEY_EXPIRY_WARNING)

    d, pc = engine_definitions, poll_cursors
    # The live workflows of a team that watch a mailbox, and when one of them last read it.
    serving = (
        sa.select(
            d.c.team_id,
            d.c.mailbox,
            sa.func.count(sa.distinct(d.c.workflow_id)).label("n"),
            sa.func.min(d.c.workflow_id).label("first"),
            sa.func.max(pc.c.updated_at).label("read_at"),
        )
        .select_from(
            d.outerjoin(
                pc,
                sa.and_(pc.c.tenant_id == d.c.tenant_id, pc.c.binding_id == sa.literal("email:") + d.c.workflow_id),
            )
        )
        .where(d.c.tenant_id == tenant, d.c.stage == "live", d.c.mailbox.is_not(None))
        .group_by(d.c.team_id, d.c.mailbox)
        .subquery("serving")
    )
    m = mailboxes
    email = (
        sa.select(
            sa.literal("email").label("type"),
            m.c.id,
            m.c.name,
            m.c.address.label("detail"),
            m.c.team_id,
            _int(m.c.paused).label("paused"),
            sa.case(
                (m.c.paused == sa.true(), "idle"),
                (serving.c.n.is_(None), "idle"),
                (serving.c.read_at.is_(None), "warn"),
                (serving.c.read_at < stale, "warn"),
                else_="ok",
            ).label("health"),
            (sa.literal(RANK["email"]) + m.c.name).label("sort"),
            _text().label("retired_at"),
            _text("workflow").label("serves_kind"),
            sa.cast(serving.c.first, sa.String(320)).label("serves_id"),
            sa.cast(sa.null(), sa.Integer).label("pinned"),
            sa.func.coalesce(serving.c.n, 0).label("serves_count"),
            sa.cast(serving.c.read_at, sa.String(320)).label("read_at"),
            _text().label("expires_at"),
            _text().label("key_status"),
        )
        .select_from(m.outerjoin(serving, sa.and_(serving.c.team_id == m.c.team_id, serving.c.mailbox == m.c.address)))
        .where(m.c.tenant_id == tenant, m.c.team_id.in_(teams), any_team(m, ASKED_TEAMS))
    )
    w = widget_deployments
    chat = sa.select(
        sa.literal("chat").label("type"),
        w.c.id,
        w.c.name,
        # Searched over every allowed website; the reply shows the first.
        sa.cast(w.c.origins, sa.Text).label("detail"),
        w.c.team_id,
        _int(w.c.paused).label("paused"),
        sa.case(
            (w.c.retired_at.is_not(None), "idle"),
            (w.c.paused == sa.true(), "idle"),
            (sa.cast(w.c.origins, sa.Text) == "[]", "error"),
            else_="ok",
        ).label("health"),
        (sa.literal(RANK["chat"]) + w.c.name).label("sort"),
        sa.cast(w.c.retired_at, sa.String(320)).label("retired_at"),
        _text("agent").label("serves_kind"),
        sa.cast(w.c.agent_id, sa.String(320)).label("serves_id"),
        w.c.agent_version.label("pinned"),
        sa.literal(1).label("serves_count"),
        _text().label("read_at"),
        _text().label("expires_at"),
        _text().label("key_status"),
    ).where(
        w.c.tenant_id == tenant,
        w.c.team_id.in_(teams),
        any_team(w, ASKED_TEAMS),
        *([] if retired else [w.c.retired_at.is_(None)]),
    )
    k = api_key_copies
    api = sa.select(
        sa.literal("api").label("type"),
        k.c.id,
        k.c.name,
        k.c.prefix.label("detail"),
        k.c.team_id,
        sa.literal(0).label("paused"),
        sa.case(
            (k.c.status == "disabled", "error"),
            (sa.and_(k.c.expires_at.is_not(None), k.c.expires_at <= now_at), "error"),
            (sa.and_(k.c.expires_at.is_not(None), k.c.expires_at < warn_at), "warn"),
            (k.c.target_kind.is_(None), "warn"),
            else_="ok",
        ).label("health"),
        (sa.literal(RANK["api"]) + k.c.name).label("sort"),
        _text().label("retired_at"),
        sa.cast(k.c.target_kind, sa.String(320)).label("serves_kind"),
        sa.cast(k.c.target_id, sa.String(320)).label("serves_id"),
        k.c.target_version.label("pinned"),
        sa.case((k.c.target_kind.is_(None), 0), else_=1).label("serves_count"),
        _text().label("read_at"),
        sa.cast(k.c.expires_at, sa.String(320)).label("expires_at"),
        sa.cast(k.c.status, sa.String(320)).label("key_status"),
    ).where(
        k.c.tenant_id == tenant,
        k.c.team_id.in_(teams),
        any_team(k, ASKED_TEAMS),
        copies.live(k),
        # A revoked key starts nothing and is kept only for the audit trail, so it is no channel.
        k.c.status != "revoked",
    )
    if agent_id is not None:
        # The channels serving one agent: its embeds and the keys that start it.
        chat = chat.where(w.c.agent_id == agent_id)
        api = api.where(k.c.target_kind == "agent", k.c.target_id == agent_id)
        email = email.where(sa.false())
    return sa.union_all(email, chat, api).subquery("channels")


class ChannelList(RuntimeStore):
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    async def live_definitions(self, teams: Sequence[str] | None = None) -> list[LiveDefinition]:
        """The tenant's live workflow versions, with their definitions; with `teams`, only those of the teams (a
        workflow no team owns is left out, as its name belongs to no team the caller was checked against)."""
        d = engine_definitions
        q = sa.select(d.c.workflow_id, d.c.name, d.c.version, d.c.definition, d.c.team_id).where(
            d.c.tenant_id == current_tenant(), d.c.stage == "live", d.c.archived_at.is_(None)
        )
        if teams is not None:
            q = q.where(d.c.team_id.in_(list(teams)))
        async with self.tx() as c:
            return await rows(c, q, LiveDefinition)

    async def published_version(self, agent_id: str) -> Any:
        """The agent's published version, None when it has none, NOT_FOUND when there is no such agent."""
        a = registry_agents
        async with self.tx() as c:
            row = (await c.execute(sa.select(a.c.published_version).where(a.c.id == agent_id, team_visible(a)))).first()
        return NOT_FOUND if row is None else row[0]

    async def page(
        self,
        teams: Sequence[str],
        params: ListParams,
        *,
        now: datetime | None = None,
        retired: bool = False,
        agent_id: str | None = None,
    ) -> Listed:
        """One page of the list with its total and facets (`type`, `health`), each row with what it serves and its
        traffic, and `kinds` over the caller's whole live list; one transaction."""
        at = now or datetime.now(UTC)
        u = channels(teams, now=at, retired=retired, agent_id=agent_id)
        async with self.tx() as c:
            listed = await list_page(
                c,
                sa.select(u),
                params,
                key=(u.c.type, u.c.id),
                search=[u.c.name, u.c.detail],
                default_sort=u.c.sort,
                filters={"type": u.c.type, "health": u.c.health},
                facets={"type": u.c.type, "health": u.c.health},
            )
            found = await _details(c, [ChannelRecord.model_validate(r) for r in listed["data"]], at)
            kinds = await _kinds(c, teams, at)
        listed["data"] = []
        return Listed(listed, found, kinds)

    async def rows(
        self,
        teams: Sequence[str],
        *,
        now: datetime | None = None,
        ids: Sequence[str] | None = None,
        agent_id: str | None = None,
        mailbox: tuple[str, str] | None = None,
        types: Sequence[str] = (),
    ) -> list[ChannelRecord]:
        """Every channel named by `ids`, serving `agent_id`, or (team, address) `mailbox`, in the list's order and with
        the same details, for a reply about one channel or an agent's or workflow's live places."""
        at = now or datetime.now(UTC)
        u = channels(teams, now=at, agent_id=agent_id)
        q = sa.select(u).order_by(u.c.sort, u.c.type, u.c.id)
        if ids is not None:
            q = q.where(u.c.id.in_(ids))
        if types:
            q = q.where(u.c.type.in_(types))
        if mailbox is not None:
            q = q.where(u.c.type == "email", u.c.team_id == mailbox[0], u.c.detail == mailbox[1])
        async with self.tx() as c:
            found = [ChannelRecord.model_validate(r) for r in (await c.execute(q)).mappings()]
            return await _details(c, found, at)


async def _kinds(c: AsyncConnection, teams: Sequence[str], at: datetime) -> list[KindCount]:
    """Per type: how many channels, how many running, how many need attention and the worst health; one GROUP BY."""
    u = channels(teams, now=at)
    worst = sa.case(*((u.c.health == s, n) for s, n in WORST.items()), else_=0)
    q = sa.select(
        u.c.type,
        sa.func.count(),
        sa.func.sum(sa.case((u.c.paused == 0, 1), else_=0)),
        sa.func.sum(sa.case((u.c.health.in_(("warn", "error")), 1), else_=0)),
        sa.func.max(worst),
    ).group_by(u.c.type)
    by_rank = {n: s for s, n in WORST.items()}
    return [
        KindCount(str(t), int(n), int(active or 0), int(attention or 0), by_rank.get(int(w)) if n else None)
        for t, n, active, attention, w in (await c.execute(q)).all()
    ]


async def _details(c: AsyncConnection, rows: list[ChannelRecord], at: datetime) -> list[ChannelRecord]:
    """The listed rows with their traffic, what they serve by name and version, and a chat row's embed settings,
    read for these rows only: a statement per kind of detail, whatever the number of rows."""
    if not rows:
        return rows
    day, week = _iso(at - timedelta(days=1)), _iso(at - timedelta(days=7))
    tenant = current_tenant()
    by_type: dict[str, list[ChannelRecord]] = {}
    for r in rows:
        by_type.setdefault(r.type, []).append(r)
    email, chat, api = by_type.get("email", []), by_type.get("chat", []), by_type.get("api", [])
    e, r_, t = trigger_events, engine_runs, graph_threads

    if email:
        sources = [f"email:{m.detail}" for m in email]
        mail = {s: Counts() for s in sources}
        q = (
            sa.select(
                e.c.source,
                sa.func.count(sa.case((e.c.recorded_at >= day, 1))),
                sa.func.count(sa.case((e.c.recorded_at >= week, 1))),
                sa.func.max(e.c.recorded_at),
            )
            .where(e.c.tenant_id == tenant, e.c.source.in_(sources), team_visible(e))
            .group_by(e.c.source)
        )
        for source, n_day, n_week, last in (await c.execute(q)).all():
            mail[str(source)] = Counts(int(n_day), 0, int(n_week), last)
        starters = [f"trigger:email:{m.detail}" for m in email]
        q = (
            sa.select(r_.c.created_by, r_.c.team_id, sa.func.count())
            .where(
                r_.c.tenant_id == tenant,
                team_visible(r_),
                r_.c.created_by.in_(starters),
                r_.c.status == "failed",
                r_.c.created_at >= day,
            )
            .group_by(r_.c.created_by, r_.c.team_id)
        )
        failed: dict[tuple[str, str], int] = {}
        for who, team, n in (await c.execute(q)).all():
            failed[(str(who)[len("trigger:") :], str(team))] = int(n)
        for m in email:
            m.counts = mail[f"email:{m.detail}"]
            m.counts.errors24h = failed.get((f"email:{m.detail}", m.team_id), 0)

    if chat:
        w = widget_deployments
        # The page's embeds, which the union chose by the caller's teams.
        q = sa.select(w.c.id, w.c.origins, w.c.agent_version).where(
            w.c.tenant_id == tenant, w.c.id.in_([x.id for x in chat]), any_team(w, ASKED_TEAMS)
        )
        embeds = {
            str(i): [str(o) for o in cast(list[object], origins or [])] for i, origins, _ in (await c.execute(q)).all()
        }
        q = (
            sa.select(
                t.c.deployment_id,
                sa.func.count(sa.case((t.c.created_at >= day, 1))),
                sa.func.count(sa.case((sa.and_(t.c.created_at >= day, t.c.status == "error"), 1))),
                sa.func.count(sa.case((t.c.created_at >= week, 1))),
                sa.func.max(t.c.updated_at),
            )
            .where(t.c.tenant_id == tenant, t.c.deployment_id.in_([x.id for x in chat]), team_visible(t))
            .group_by(t.c.deployment_id)
        )
        counted = {str(i): Counts(int(a), int(b), int(n), last) for i, a, b, n, last in (await c.execute(q)).all()}
        mk = widget_mint_keys
        q = (
            sa.select(mk.c.deployment_id, sa.func.count())
            .where(mk.c.tenant_id == tenant, mk.c.deployment_id.in_([x.id for x in chat]), mk.c.revoked_at.is_(None))
            .group_by(mk.c.deployment_id)
        )
        # Unrevoked mint keys per embed.
        minting = {str(i): int(n) for i, n in (await c.execute(q)).all()}
        for x in chat:
            x.origins = embeds.get(x.id, [])
            x.counts = counted.get(str(x.id), Counts())
            x.active_keys = minting.get(str(x.id), 0)

    if api:
        starters = [f"key:{k.id}" for k in api]
        counts: dict[str, Counts] = {s: Counts() for s in starters}
        thread_starter = t.c.meta["startedBy"].as_string()
        q = (
            sa.select(
                r_.c.created_by,
                sa.func.count(sa.case((r_.c.created_at >= day, 1))),
                sa.func.count(sa.case((sa.and_(r_.c.created_at >= day, r_.c.status == "failed"), 1))),
                sa.func.count(sa.case((r_.c.created_at >= week, 1))),
                sa.func.max(r_.c.created_at),
            )
            .where(r_.c.tenant_id == tenant, r_.c.created_by.in_(starters))
            .group_by(r_.c.created_by)
        )
        for who, n_day, n_err, n_week, last in (await c.execute(q)).all():
            counts[str(who)] = Counts(int(n_day), int(n_err), int(n_week), last)
        q = (
            sa.select(
                thread_starter,
                sa.func.count(sa.case((t.c.created_at >= day, 1))),
                sa.func.count(sa.case((sa.and_(t.c.created_at >= day, t.c.status == "error"), 1))),
                sa.func.count(sa.case((t.c.created_at >= week, 1))),
                sa.func.max(t.c.updated_at),
            )
            .where(t.c.tenant_id == tenant, thread_starter.in_(starters))
            .group_by(thread_starter)
        )
        for who, n_day, n_err, n_week, last in (await c.execute(q)).all():
            was = counts[str(who)]
            counts[str(who)] = Counts(
                was.traffic24h + int(n_day),
                was.errors24h + int(n_err),
                was.activity7d + int(n_week),
                max(filter(None, (was.last_activity_at, last)), default=None),
            )
        for k in api:
            k.counts = counts[f"key:{k.id}"]

    # What each row serves, by name and latest version: live workflows for mailboxes and workflow keys, the registry
    # for embeds and agent keys.
    workflow_ids = {str(x.serves_id) for x in rows if x.serves_kind == "workflow" and x.serves_id}
    agent_ids = {str(x.serves_id) for x in rows if x.serves_kind == "agent" and x.serves_id}
    workflows: dict[str, tuple[str, int | None]] = {}
    if workflow_ids:
        d = engine_definitions
        q = sa.select(d.c.workflow_id, d.c.name, d.c.version).where(
            d.c.tenant_id == tenant, d.c.stage == "live", d.c.workflow_id.in_(workflow_ids)
        )
        workflows = {str(i): (str(n or i), v) for i, n, v in (await c.execute(q)).all()}
    agents: dict[str, tuple[str, int | None]] = {}
    if agent_ids:
        a, v = registry_agents, registry_agent_versions
        q = (
            sa.select(a.c.id, v.c.spec["name"].as_string(), a.c.published_version)
            .select_from(a.join(v, sa.and_(v.c.agent_id == a.c.id, v.c.version == a.c.version)))
            .where(a.c.id.in_(agent_ids), team_visible(a))
        )
        agents = {str(i): (str(n or i), p) for i, n, p in (await c.execute(q)).all()}
    for x in rows:
        target = x.serves_id
        named = (workflows if x.serves_kind == "workflow" else agents).get(target) if target else None
        x.serves_name, x.latest_version = named or (target, None)
    return rows
