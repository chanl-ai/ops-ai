"""GET /v1/channels: every channel the caller's teams run, one row per existing record (a mailbox is email, a
widget deployment is chat), with what it serves, a health dot from real checks, and its traffic, so the Channels hub
neither joins records nor counts anything itself. `kinds` gives the gallery one row per channel type.

Retiring a chat channel answers in one request transaction (`Tx`). Every other route takes none: each reply asks
platform-service for the teams' names (`replies`), and a change may ask it for the team's publish-review setting, so
each store call takes and returns its own connection and none is held while platform-service answers. The list itself
is one union of mailboxes, embeds and the local copy of platform's API keys, paged in SQL (store.channel_list).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal, TypeAlias, cast

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ops_access import can
from ops_identity.fastapi import Tx
from ops_service_kit.errors import Conflict, Forbidden, NotFound, Unprocessable
from ops_service_kit.http import Envelope, In, ListResult, Out
from ops_service_kit.ids import now_iso
from ops_service_kit.listing import ListParams
from ops_store import isolation

from ...store.channel_list import (
    KEY_EXPIRY_WARNING,
    NOT_FOUND,
    ChannelList,
    ChannelRecord,
    KindCount,
    watched_address,
)
from ...store.mailboxes import MailboxStore
from ...store.widget_deployments import WidgetDeployments
from .. import deployment_reviews
from ..auth import Principal, caller_in, caller_of, require_builder
from ..deps import Runtime, runtime
from ..envelope import ok
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
# The gallery's order; the last two are coming soon. MCP is built, but its page is the gateway's own, not rows here.
KINDS: tuple[tuple[str, bool], ...] = (
    ("api", True),
    ("chat", True),
    ("email", True),
    ("mcp", True),
    ("slack", False),
    ("teams", False),
)


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


def _reason(row: ChannelRecord, now: datetime) -> str | None:
    """Why a row is in its health state (the state is the store's, in SQL), for the dot's tooltip."""
    state, kind = row.health, row.type
    if kind == "email":
        if state == "idle":
            return "Paused" if row.paused else "No live workflow watches this mailbox"
        if state == "warn":
            read = row.read_at
            if read is None:
                return "Not read yet"
            age = now - datetime.fromisoformat(str(read).replace("Z", "+00:00"))
            return f"Not read for {int(age.total_seconds() // 60)} minutes"
        return None
    if kind == "chat":
        if state == "idle":
            return "Retired" if row.retired_at else "Paused"
        return "No allowed websites" if state == "error" else None
    if state == "ok":
        return None
    expires = row.expires_at
    left = datetime.fromisoformat(str(expires).replace("Z", "+00:00")) - now if expires else None
    if state == "error":
        return "Disabled: its creator left the team" if row.key_status == "disabled" else "Expired"
    if left is not None and left < KEY_EXPIRY_WARNING:
        return f"Expires in {max(1, left.days)} days"
    return "Starts any live workflow of its team"


def _counts(c: Any) -> dict[str, Any]:
    return {
        "traffic24h": c.traffic24h,
        "errors24h": c.errors24h,
        "activity7d": c.activity7d,
        "lastActivityAt": c.last_activity_at,
    }


def _serves(row: ChannelRecord) -> dict[str, Any] | None:
    if not row.serves_id:
        return None
    pinned, latest = row.pinned, row.latest_version
    return {
        "kind": row.serves_kind,
        "id": row.serves_id,
        "name": row.serves_name,
        # A mailbox serves its workflows' live version; an embed or key its pin, or Latest.
        "version": "latest" if pinned is None else int(pinned),
        "latestVersion": latest,
        "behind": max(0, int(latest) - int(pinned)) if latest is not None and pinned is not None else 0,
    }


async def replies(rt: Runtime, me: Principal, rows: list[ChannelRecord], now: datetime) -> list[dict[str, Any]]:
    """The store's rows as the list answers them; asks platform-service for the teams' names with no transaction
    open."""
    names = rt.team_names if isinstance(rt.team_names, PlatformTeamNames) else None
    out: list[dict[str, Any]] = []
    for r in rows:
        checked = _iso(now)
        reason = _reason(r, now)
        origins = r.origins
        row: dict[str, Any] = {
            "id": r.id,
            "type": r.type,
            "name": r.name,
            "detail": next(iter(origins), "") if r.type == "chat" else r.detail,
            "teamId": r.team_id,
            "teamName": await names.name(r.team_id) if names is not None else None,
            "serves": _serves(r),
            "servesCount": r.serves_count,
            "health": {"state": r.health, "checkedAt": checked} | ({"reason": reason} if reason else {}),
            "paused": bool(r.paused),
            **_counts(r.counts),
            # An API key changes in Settings, API keys, on platform-service: nothing here edits it.
            "canEdit": r.type != "api" and _may(me, "edit", r.team_id),
        }
        if r.type == "chat":
            pinned, latest = r.pinned, r.latest_version
            row["embed"] = {
                "agentId": r.serves_id,
                "agentVersion": int(pinned) if pinned is not None else latest,
                "origins": origins,
                "retiredAt": r.retired_at,
                "activeKeys": r.active_keys,
            }
        out.append(row)
    return out


def kinds_of(counted: list[KindCount]) -> list[dict[str, Any]]:
    by_type = {k.type: k for k in counted}
    out: list[dict[str, Any]] = []
    for kind, built in KINDS:
        k = by_type.get(kind)
        out.append(
            {
                "type": kind,
                "built": built,
                "health": k.worst if k else None,
                "active": k.active if k else 0,
                "attention": k.attention if k else 0,
                "total": k.total if k else 0,
            }
        )
    return out


@router.get("", response_model=Envelope[ChannelPage])
async def list_channels(rt: Rt, me: Me, q: Annotated[ChannelsQuery, Query()]) -> JSONResponse:
    """The channels of the selected team (`team=all`: every team the caller is in and may view channels of), filtered
    by type, health and a search over name and detail, in the list's order (email, chat, then API, each by name), a
    page at a time from one statement over the three (store.channel_list); a page past the end answers the last page.
    `facets` count by type and health under the other filters; `kinds` describes every channel type, built or not,
    over the caller's whole list."""
    asked = _teams(me, q.team)
    teams = tuple(t for t in asked if _may(me, "view", t))
    now = datetime.now(UTC)
    params = ListParams(
        page=q.page,
        search=q.search,
        filters={k: list(v) for k, v in (("type", q.type), ("health", q.health)) if v},
    ).model_copy(update={"page_size": q.pageSize})
    listed = await ChannelList(rt.db).page(teams, params, now=now, retired=q.includeRetired, agent_id=q.agentId)
    page = listed.page | {"data": await replies(rt, me, listed.rows, now)}
    return ok(page | {"kinds": kinds_of(listed.kinds)})


async def channel_row(rt: Runtime, me: Principal, channel_id: str, teams: tuple[str, ...]) -> dict[str, Any]:
    now = datetime.now(UTC)
    found = await replies(rt, me, await ChannelList(rt.db).rows(teams, now=now, ids=[channel_id]), now)
    if not found:
        raise NotFound(f"Channel {channel_id}")
    return found[0]


class ChannelIn(In):
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
    return ok(await channel_row(rt, me, str(made["id"]), (str(made["team_id"]),)), 201)


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
    teams = tuple(t for t in asked if _may(me, "view", t))
    now = datetime.now(UTC)
    async with isolation.request_transaction():
        latest = await ChannelList(rt.db).published_version(agent_id)
        if latest is NOT_FOUND:
            raise NotFound(f"Agent {agent_id}")
        serving = await ChannelList(rt.db).rows(teams, now=now, agent_id=agent_id, types=["chat"])
        live = await ChannelList(rt.db).live_definitions()
    rows = [_place(r) for r in await replies(rt, me, serving, now)]
    rows += _steps(live, "ops.ai.agent", "agent", agent_id, cast(int | None, latest))
    return ok({"latestVersion": latest, "versions": _versions(rows, cast(int | None, latest)), "rows": rows})


@live_router.get("/v1/workflows/{workflow_id}/live", response_model=Envelope[Live])
async def workflow_live(rt: Rt, me: Me, workflow_id: str) -> JSONResponse:
    """Where the workflow serves: the email channels whose trigger it is, and the live steps that start it."""
    asked = _teams(me, "all")
    teams = tuple(t for t in asked if _may(me, "view", t))
    live = await ChannelList(rt.db).live_definitions()
    mine = next((d for d in live if d["workflow_id"] == workflow_id), None)
    if mine is None or mine["team_id"] not in teams:
        raise NotFound(f"Live workflow {workflow_id}")
    latest = int(mine["version"])
    address = watched_address(mine["definition"])
    now = datetime.now(UTC)
    watching = await ChannelList(rt.db).rows(teams, now=now, mailbox=(str(mine["team_id"]), address)) if address else []
    rows = [_place(r) for r in await replies(rt, me, watching, now)]
    rows += _steps(live, "ops.action.workflow", "workflow", workflow_id, latest)
    return ok({"latestVersion": latest, "versions": _versions(rows, latest), "rows": rows})


class ServesPatch(In):
    kind: Literal["workflow", "agent"]
    id: str
    version: int | Literal["latest"]


class ChannelPatch(In):
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
        if row is None or row["team_id"] not in me.team_ids:
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
        if found is None or found.team_id not in me.team_ids:
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
    return ok(await channel_row(rt, me, channel_id, me.team_ids))


@router.post("/{channel_id}/retire", response_model=Envelope[Retired])
async def retire_channel(rt: Rt, me: Me, channel_id: str, _: Tx) -> JSONResponse:
    """Retires a chat channel for good: the embed answers no page again and cannot be changed. An email channel
    is removed on its mailbox's page, and an API channel is a key revoked in Settings."""
    if not channel_id.startswith("wd_"):
        raise Conflict("Only a chat channel is retired here.", code="channel_managed_elsewhere")
    store = WidgetDeployments(rt.db)
    row = await store.get(channel_id)
    if row is None or row["team_id"] not in me.team_ids:
        raise NotFound(f"Channel {channel_id}")
    require_builder(me, area="deployments", team_id=str(row["team_id"]), action="edit", what=WHAT)
    at = now_iso()
    if not await store.retire(channel_id, at):
        raise Conflict("This channel is retired already.", code="channel_retired")
    return ok({"id": channel_id, "retiredAt": at})


WHAT = "this channel"
