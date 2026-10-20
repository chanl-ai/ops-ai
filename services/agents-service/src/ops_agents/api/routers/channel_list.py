"""GET /v1/channels (c-245): every channel the caller's teams run, one row per existing record (a mailbox is email, a
widget deployment is chat), with what it serves, a health dot from real checks, and its traffic, so the Channels hub
neither joins records nor counts anything itself. `kinds` gives the gallery one row per channel type."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, TypeAlias, cast

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ops_access import can
from ops_contracts.chat import WireModel
from ops_service_kit.errors import Conflict, Forbidden, NotFound, Unprocessable
from ops_service_kit.http import Envelope, ListResult, paged
from ops_service_kit.ids import now_iso

from ...store.channel_list import NOT_FOUND, STALE_READ, ChannelList
from ...store.mailboxes import MailboxStore
from ...store.widget_deployments import WidgetDeployments
from ...store.widget_keys import WidgetKeys
from .. import deployment_reviews
from ..auth import Principal, caller_in, caller_of, require_builder
from ..deps import Runtime, runtime
from ..envelope import ok
from ..schemas import Out
from ..team_names import PlatformTeamNames
from ..widget_sessions import normal_origin
from .activity import _teams  # pyright: ignore[reportPrivateUsage]
from .widget import WidgetDeploymentInput, make_deployment, served_version

Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(caller_in("deployments"))]  # noqa: UP040

router = APIRouter(prefix="/v1/channels")

ChannelType = Literal["email", "chat", "api"]
# Every kind the gallery shows: a filter may name one not built yet, whose page lists nothing.
KindType = Literal["email", "chat", "api", "mcp", "slack", "teams"]
HealthState = Literal["ok", "warn", "error", "idle"]
# The gallery's order; the last three are coming soon.
KINDS: tuple[tuple[str, bool], ...] = (
    ("api", True),
    ("chat", True),
    ("email", True),
    ("mcp", False),
    ("slack", False),
    ("teams", False),
)
WORST = {"error": 3, "warn": 2, "ok": 1, "idle": 0}


class Serves(Out):
    kind: Literal["workflow", "agent"]
    id: str
    name: str
    # "latest", or the pinned version.
    version: int | Literal["latest"]
    latest_version: int | None
    behind: int


class Health(Out):
    state: HealthState
    reason: str | None = None
    checked_at: str


class Embed(Out):
    """A chat channel's embed settings, for an agent's embed table."""

    agent_id: str
    # The version it answers from now: its pin, or on Latest the agent's newest published one.
    agent_version: int | None
    origins: list[str]
    retired_at: str | None
    # Unrevoked mint keys.
    active_keys: int


class ChannelRow(Out):
    # The record's own id: mbx_ for a mailbox, wd_ for a widget deployment, key_ for an API key.
    id: str
    type: ChannelType
    name: str
    # The address, the first allowed website, or the key's prefix.
    detail: str
    team_id: str
    team_name: str | None
    serves: Serves | None
    # Email: how many live workflows watch the mailbox (`serves` is the first).
    serves_count: int
    health: Health
    paused: bool
    traffic24h: int | None
    errors24h: int | None
    activity7d: int | None
    last_activity_at: str | None
    can_edit: bool
    # Chat channels only.
    embed: Embed | None = None


class KindRow(Out):
    type: str
    built: bool
    # The worst health of the type's channels; None when it has none.
    health: HealthState | None
    active: int
    attention: int
    total: int


class ChannelPage(ListResult[ChannelRow]):
    kinds: list[KindRow]


class ChannelsQuery(BaseModel):
    type: list[KindType] = Field(default_factory=list[KindType])
    health: list[HealthState] = Field(default_factory=list[HealthState])
    search: str | None = None
    # The selected team when left out; `all` for every team the caller is in.
    team: str | None = None
    # The channels serving this agent: an agent's embed table.
    agentId: str | None = None  # noqa: N815 - the console's query parameter
    # Retired chat channels too, which Channels leaves out.
    includeRetired: bool = False  # noqa: N815
    page: int = Field(default=1, ge=1)
    pageSize: int = Field(default=50, ge=1, le=200)  # noqa: N815 - the console's query parameter


def _may(me: Principal, action: str, team: str) -> bool:
    try:
        can(caller_of(me), "deployments", action, team=team, what="this channel", from_any_team=True)
    except Forbidden:
        return False
    return True


def _iso(at: datetime) -> str:
    return at.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def email_health(row: dict[str, Any], now: datetime) -> dict[str, Any]:
    checked = _iso(now)
    if row["paused"]:
        return {"state": "idle", "reason": "Paused", "checkedAt": checked}
    if not row["serving"]:
        return {"state": "idle", "reason": "No live workflow watches this mailbox", "checkedAt": checked}
    read = row["last_read_at"]
    if read is None:
        return {"state": "warn", "reason": "Not read yet", "checkedAt": checked}
    age = now - datetime.fromisoformat(str(read).replace("Z", "+00:00"))
    if age > STALE_READ:
        return {
            "state": "warn",
            "reason": f"Not read for {int(age.total_seconds() // 60)} minutes",
            "checkedAt": checked,
        }
    return {"state": "ok", "checkedAt": checked}


def chat_health(row: dict[str, Any], now: datetime) -> dict[str, Any]:
    checked = _iso(now)
    if row.get("retired_at"):
        return {"state": "idle", "reason": "Retired", "checkedAt": checked}
    if row["paused"]:
        return {"state": "idle", "reason": "Paused", "checkedAt": checked}
    if not list(row["origins"] or []):
        return {"state": "error", "reason": "No allowed websites", "checkedAt": checked}
    return {"state": "ok", "checkedAt": checked}


# A key expiring sooner than this is amber, so someone rotates it before the systems calling it start failing.
KEY_EXPIRY_WARNING = timedelta(days=14)


def api_health(key: dict[str, Any], now: datetime) -> dict[str, Any]:
    checked = _iso(now)
    if key["status"] == "disabled":
        return {"state": "error", "reason": "Disabled: its creator left the team", "checkedAt": checked}
    expires = key.get("expiresAt")
    if expires:
        left = datetime.fromisoformat(str(expires).replace("Z", "+00:00")) - now
        if left <= timedelta(0):
            return {"state": "error", "reason": "Expired", "checkedAt": checked}
        if left < KEY_EXPIRY_WARNING:
            return {"state": "warn", "reason": f"Expires in {max(1, left.days)} days", "checkedAt": checked}
    if not key.get("target"):
        return {"state": "warn", "reason": "Starts any live workflow of its team", "checkedAt": checked}
    return {"state": "ok", "checkedAt": checked}


def _counts(c: Any) -> dict[str, Any]:
    return {
        "traffic24h": c.traffic24h,
        "errors24h": c.errors24h,
        "activity7d": c.activity7d,
        "lastActivityAt": c.last_activity_at,
    }


async def rows_of(
    rt: Runtime, me: Principal, teams: tuple[str, ...] | None, *, retired: bool = False
) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    listed = await ChannelList(rt.db).rows(teams, now=now, retired=retired)
    keys_of = await WidgetKeys(rt.db).active_counts([str(w["id"]) for w in listed.chat])
    names = rt.team_names if isinstance(rt.team_names, PlatformTeamNames) else None
    out: list[dict[str, Any]] = []
    for m in listed.email:
        first = m["serving"][0] if m["serving"] else None
        serves = first and {
            "kind": "workflow",
            "id": first["workflow_id"],
            "name": first["name"] or first["workflow_id"],
            "version": "latest",
            "latestVersion": first["version"],
            "behind": 0,
        }
        out.append(
            {
                "id": m["id"],
                "type": "email",
                "name": m["name"],
                "detail": m["address"],
                "teamId": m["team_id"],
                "serves": serves,
                "servesCount": len(m["serving"]),
                "health": email_health(m, now),
                "paused": bool(m["paused"]),
                **_counts(m["counts"]),
            }
        )
    for w in listed.chat:
        pinned = w["agent_version"]
        latest = w["published_version"]
        version = "latest" if pinned is None else int(pinned)
        out.append(
            {
                "id": w["id"],
                "type": "chat",
                "name": w["name"],
                "detail": next(iter(list(w["origins"] or [])), ""),
                "teamId": w["team_id"],
                "serves": {
                    "kind": "agent",
                    "id": w["agent_id"],
                    "name": w["agent_name"],
                    "version": version,
                    "latestVersion": latest,
                    "behind": max(0, int(latest) - int(pinned)) if latest is not None and pinned is not None else 0,
                },
                "servesCount": 1,
                "health": chat_health(w, now),
                "paused": bool(w["paused"]),
                **_counts(w["counts"]),
                "embed": {
                    "agentId": w["agent_id"],
                    "agentVersion": int(pinned) if pinned is not None else latest,
                    "origins": list(w["origins"] or []),
                    "retiredAt": w.get("retired_at"),
                    "activeKeys": keys_of.get(str(w["id"]), 0),
                },
            }
        )
    keys = cast(list[dict[str, Any]] | None, await rt.key_summaries.list() if rt.key_summaries is not None else None)
    # A revoked key starts nothing and is kept only for the audit trail, so it is no channel.
    mine = [k for k in keys or [] if k["status"] != "revoked" and (teams is None or k["teamId"] in teams)]
    for k in await ChannelList(rt.db).api_rows(mine, now=now):
        target = k["target"]
        serves = None
        if target:
            pinned, latest = target.get("version"), k["latest_version"]
            serves = {
                "kind": target["kind"],
                "id": target["id"],
                "name": k["serves_name"],
                "version": "latest" if pinned is None else int(pinned),
                "latestVersion": latest,
                "behind": max(0, int(latest) - int(pinned)) if latest is not None and pinned is not None else 0,
            }
        out.append(
            {
                "id": k["id"],
                "type": "api",
                "name": k["name"],
                "detail": k["prefix"],
                "teamId": k["teamId"],
                "serves": serves,
                "servesCount": 1 if serves else 0,
                "health": api_health(k, now),
                "paused": False,
                **_counts(k["counts"]),
            }
        )
    for row in out:
        row["teamName"] = await names.name(row["teamId"]) if names is not None else None
        # An API key changes in Settings, API keys, on platform-service: nothing here edits it.
        row["canEdit"] = row["type"] != "api" and _may(me, "edit", row["teamId"])
    return out


def kinds_of(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for kind, built in KINDS:
        mine = [r for r in rows if r["type"] == kind]
        states = [r["health"]["state"] for r in mine]
        out.append(
            {
                "type": kind,
                "built": built,
                "health": max(states, key=lambda s: WORST[s]) if states else None,
                "active": sum(1 for r in mine if not r["paused"]),
                "attention": sum(1 for s in states if s in ("warn", "error")),
                "total": len(mine),
            }
        )
    return out


def _retired(row: dict[str, Any]) -> bool:
    embed = cast(dict[str, Any] | None, row.get("embed"))
    return bool(embed and embed.get("retiredAt"))


def _serves_agent(row: dict[str, Any], agent_id: str) -> bool:
    serves = cast(dict[str, Any] | None, row["serves"])
    return bool(serves and serves["kind"] == "agent" and serves["id"] == agent_id)


@router.get("", response_model=Envelope[ChannelPage])
async def list_channels(rt: Rt, me: Me, q: Annotated[ChannelsQuery, Query()]) -> JSONResponse:
    """The channels of the selected team (`team=all`: every team the caller is in and may view channels of), filtered
    by type, health and a search over name and detail. `facets` count by type and health under the other filters;
    `kinds` describes every channel type, built or not, over the caller's whole list."""
    asked = _teams(me, q.team)
    teams = asked if asked is None else tuple(t for t in asked if _may(me, "view", t))
    rows = await rows_of(rt, me, teams, retired=q.includeRetired)
    # Kinds describe the live channels; a retired embed serves nothing.
    kinds = kinds_of([r for r in rows if not _retired(r)])
    if q.agentId:
        rows = [r for r in rows if _serves_agent(r, q.agentId)]
    if q.search:
        needle = q.search.lower()
        rows = [r for r in rows if needle in r["name"].lower() or needle in r["detail"].lower()]
    by_type = [r for r in rows if not q.health or r["health"]["state"] in q.health]
    by_health = [r for r in rows if not q.type or r["type"] in q.type]
    chosen = [r for r in by_type if not q.type or r["type"] in q.type]
    start = (q.page - 1) * q.pageSize
    listed = paged(chosen[start : start + q.pageSize], len(chosen), q.page, q.pageSize)
    facets = {
        "type": _count(str(r["type"]) for r in by_type),
        "health": _count(str(r["health"]["state"]) for r in by_health),
    }
    return ok(listed | {"facets": facets, "kinds": kinds})


class ChannelIn(WireModel):
    # Chat is the one made here; a mailbox is connected at /v1/channels/mailboxes, an API key in Settings.
    type: Literal["chat"]
    agent_id: str
    name: str = Field(min_length=1, max_length=200)
    origins: list[str] = Field(min_length=1, max_length=20)


@router.post("", response_model=Envelope[ChannelRow], status_code=201)
async def create_channel(rt: Rt, me: Me, body: ChannelIn) -> JSONResponse:
    """Connects a chat channel: the agent pinned at its published version, answering on exact origins, in the
    caller's team (builders and admins of the agent's team)."""
    made = await make_deployment(
        rt, me, WidgetDeploymentInput(name=body.name, agent_id=body.agent_id, origins=body.origins)
    )
    row = next((r for r in await rows_of(rt, me, (str(made["team_id"]),)) if r["id"] == made["id"]), None)
    if row is None:
        raise NotFound(f"Channel {made['id']}")
    return ok(row, 201)


def _count(keys: Iterable[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for k in keys:
        out[k] = out.get(k, 0) + 1
    return out


live_router = APIRouter()


class Where(Out):
    kind: Literal["channel", "workflow_step"]
    id: str
    name: str
    # A channel's type; a step's workflow id.
    type: str | None = None
    workflow_id: str | None = None


class LivePlace(Out):
    where: Where
    version: int | Literal["latest"] | None
    pinned: bool
    behind: int
    health: Health | None
    traffic24h: int | None
    errors24h: int | None
    last_activity_at: str | None


class LiveVersion(Out):
    version: int
    places: int


class Live(Out):
    latest_version: int | None
    versions: list[LiveVersion]
    rows: list[LivePlace]


def _place(row: dict[str, Any]) -> dict[str, Any]:
    serves = cast(dict[str, Any], row["serves"] or {})
    return {
        "where": {"kind": "channel", "id": row["id"], "name": row["name"], "type": row["type"]},
        "version": serves.get("version"),
        "pinned": serves.get("version") not in (None, "latest"),
        "behind": serves.get("behind") or 0,
        "health": row["health"],
        "traffic24h": row["traffic24h"],
        "errors24h": row["errors24h"],
        "lastActivityAt": row["lastActivityAt"],
    }


def _steps(
    live: list[dict[str, Any]], node_type: str, param: str, target: str, version: int | None
) -> list[dict[str, Any]]:
    """Each live workflow step that names `target`: it runs the published version, so it is never pinned."""
    out: list[dict[str, Any]] = []
    for d in live:
        definition = cast(dict[str, Any], d["definition"] or {})
        for n in cast(list[dict[str, Any]], definition.get("nodes") or []):
            params = cast(dict[str, Any], n.get("parameters") or {})
            if n.get("type") == node_type and params.get(param) == target:
                out.append(
                    {
                        "where": {
                            "kind": "workflow_step",
                            "id": str(n.get("id")),
                            "name": f"{d['name'] or d['workflow_id']}: {n.get('name') or n.get('id')}",
                            "workflowId": d["workflow_id"],
                        },
                        "version": version,
                        "pinned": False,
                        "behind": 0,
                        "health": None,
                        "traffic24h": None,
                        "errors24h": None,
                        "lastActivityAt": None,
                    }
                )
    return out


def _versions(rows: list[dict[str, Any]], latest: int | None) -> list[dict[str, Any]]:
    counts: dict[int, int] = {}
    for r in rows:
        v = latest if r["version"] == "latest" else r["version"]
        if isinstance(v, int):
            counts[v] = counts.get(v, 0) + 1
    return [{"version": v, "places": n} for v, n in sorted(counts.items(), reverse=True)]


@live_router.get("/v1/agents/{agent_id}/live", response_model=Envelope[Live])
async def agent_live(rt: Rt, me: Me, agent_id: str) -> JSONResponse:
    """Where the agent serves: the chat channels on it, pinned or on Latest, and the live workflow steps that run it."""
    asked = _teams(me, "all")
    teams = asked if asked is None else tuple(t for t in asked if _may(me, "view", t))
    latest = await ChannelList(rt.db).published_version(agent_id)
    if latest is NOT_FOUND:
        raise NotFound(f"Agent {agent_id}")
    rows = [_place(r) for r in await rows_of(rt, me, teams) if r["type"] == "chat" and r["serves"]["id"] == agent_id]
    live = await ChannelList(rt.db).live_definitions()
    rows += _steps(live, "ops.ai.agent", "agent", agent_id, cast(int | None, latest))
    return ok({"latestVersion": latest, "versions": _versions(rows, cast(int | None, latest)), "rows": rows})


@live_router.get("/v1/workflows/{workflow_id}/live", response_model=Envelope[Live])
async def workflow_live(rt: Rt, me: Me, workflow_id: str) -> JSONResponse:
    """Where the workflow serves: the email channels whose trigger it is, and the live steps that start it."""
    asked = _teams(me, "all")
    teams = asked if asked is None else tuple(t for t in asked if _may(me, "view", t))
    live = await ChannelList(rt.db).live_definitions()
    mine = next((d for d in live if d["workflow_id"] == workflow_id), None)
    if mine is None or (teams is not None and mine["team_id"] not in teams):
        raise NotFound(f"Live workflow {workflow_id}")
    latest = int(mine["version"])
    listed = await ChannelList(rt.db).rows(teams)
    watching = {m["id"] for m in listed.email if any(s["workflow_id"] == workflow_id for s in m["serving"])}
    rows = [_place(r) for r in await rows_of(rt, me, teams) if r["id"] in watching]
    rows += _steps(live, "ops.action.workflow", "workflow", workflow_id, latest)
    return ok({"latestVersion": latest, "versions": _versions(rows, latest), "rows": rows})


class ServesPatch(WireModel):
    kind: Literal["workflow", "agent"]
    id: str
    version: int | Literal["latest"]


class ChannelPatch(WireModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    paused: bool | None = None
    serves: ServesPatch | None = None
    # A chat channel's allowed websites; a change follows the team's publish-review setting, as a serves change does.
    origins: list[str] | None = Field(default=None, min_length=1, max_length=20)


class Retired(Out):
    id: str
    retired_at: str


class ChangeWaits(Out):
    # The review the change waits on, in Reviews; the channel keeps serving as it was until it is approved.
    review_id: str


@router.patch(
    "/{channel_id}",
    response_model=Envelope[ChannelRow],
    responses={202: {"model": Envelope[ChangeWaits], "description": "The serves change waits for a review"}},
)
async def update_channel(rt: Rt, me: Me, channel_id: str, body: ChannelPatch) -> JSONResponse:
    """Renames, pauses or resumes a channel, or changes a chat channel's allowed websites or what it serves: a version,
    or Latest. A websites or serves change follows the team's publish-review setting: applied at once (200 with the
    row) or held for a review (202 with its id). An email channel serves the workflows whose trigger names its mailbox,
    so it changes there, not here."""
    now = now_iso()
    if channel_id.startswith("wd_"):
        store = WidgetDeployments(rt.db)
        row = await store.get(channel_id)
        if row is None or (me.team_ids is not None and row["team_id"] not in me.team_ids):
            raise NotFound(f"Channel {channel_id}")
        require_builder(me, area="deployments", team_id=str(row["team_id"]), action="edit", what=WHAT)
        if row.get("retired_at"):
            raise Conflict("This embed is retired, so it cannot be changed.", code="widget_retired")
        values: dict[str, Any] = {"updated_at": now}
        if body.name is not None:
            values["name"] = body.name.strip()
        if body.paused is not None:
            values["paused"] = body.paused
        waits: str | None = None
        changes: dict[str, Any] = {}
        if body.origins is not None and (origins := sorted({normal_origin(o) for o in body.origins})) != list(
            row["origins"]
        ):
            changes["origins"] = origins
        if body.serves is not None:
            if body.serves.kind != "agent" or body.serves.id != row["agent_id"]:
                raise Unprocessable(
                    "A chat channel keeps its agent; connect a new channel to serve another one.",
                    code="serves_agent_fixed",
                )
            latest = body.serves.version == "latest"
            target = await served_version(rt, {**row, "agent_version": None}) if latest else int(body.serves.version)
            if (None if latest else target) != row["agent_version"]:
                changes |= {"agentVersion": target} | ({"latest": True} if latest else {})
        if changes:
            # The policy applies every change at once or holds them all in one review.
            applied = await deployment_reviews.change(rt, row, changes, by=me.email)
            if applied:
                values |= applied
            else:
                waits = await deployment_reviews.pending(rt, channel_id)
        await store.update(channel_id, **values)
        if waits is not None:
            return ok({"reviewId": waits}, 202)
    elif channel_id.startswith("mbx_"):
        boxes = MailboxStore(rt.db)
        found = await boxes.get(channel_id)
        if found is None or (me.team_ids is not None and found.team_id not in me.team_ids):
            raise NotFound(f"Channel {channel_id}")
        require_builder(me, area="deployments", team_id=found.team_id, action="edit", what=WHAT)
        if body.serves is not None:
            raise Unprocessable(
                "An email channel serves the workflows whose Email received trigger names its mailbox; change the "
                "workflow's trigger to change what it serves.",
                code="serves_from_workflow",
            )
        if body.origins is not None:
            raise Unprocessable("Allowed websites belong to a chat channel.", code="origins_chat_only")
        changed = {
            **({"paused": body.paused} if body.paused is not None else {}),
            **({"name": body.name.strip()} if body.name is not None else {}),
        }
        if changed:
            await boxes.update(channel_id, changed | {"updated_at": now})
    elif channel_id.startswith("key_"):
        raise Conflict(
            "An API channel is an API key, which changes in Settings, API keys.", code="channel_managed_elsewhere"
        )
    else:
        raise NotFound(f"Channel {channel_id}")
    row_now = next((r for r in await rows_of(rt, me, None) if r["id"] == channel_id), None)
    if row_now is None:
        raise NotFound(f"Channel {channel_id}")
    return ok(row_now)


@router.post("/{channel_id}/retire", response_model=Envelope[Retired])
async def retire_channel(rt: Rt, me: Me, channel_id: str) -> JSONResponse:
    """Retires a chat channel for good (c-130): the embed answers no page again and cannot be changed. An email channel
    is removed on its mailbox's page, and an API channel is a key revoked in Settings."""
    if not channel_id.startswith("wd_"):
        raise Conflict("Only a chat channel is retired here.", code="channel_managed_elsewhere")
    store = WidgetDeployments(rt.db)
    row = await store.get(channel_id)
    if row is None or (me.team_ids is not None and row["team_id"] not in me.team_ids):
        raise NotFound(f"Channel {channel_id}")
    require_builder(me, area="deployments", team_id=str(row["team_id"]), action="edit", what=WHAT)
    at = now_iso()
    if not await store.retire(channel_id, at):
        raise Conflict("This channel is retired already.", code="channel_retired")
    return ok({"id": channel_id, "retiredAt": at})


WHAT = "this channel"
