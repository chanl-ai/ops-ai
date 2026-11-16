"""Widget deployments and the widget API: an agent's chat on a page on another origin.

`/v1/widget-deployments` is for the team that owns the agent: make a deployment (it pins the agent's published version
and lists the exact origins allowed to use it), list, change origins, pause, move to the newest published version, and
issue the per-deployment mint keys a bank's server mints sessions with. `/v1/widget/{deployment}` is for the
page: exchange the bank's SSO token for a session, then start, read and continue conversations through the same chat
code the console uses, as the public-key caller class, so budgets and guardrails apply exactly as there.

A route that only reads and writes this service's database answers in one request transaction (`Tx`), taken before
the credential is read, so the key or session check, the deployment read and any write land together or not at all.
Three page routes take none, so no connection is held while another party answers: starting a conversation (chat's
start may ask kb-service for the agent's knowledge bases), a message (a model turn, streamed) and continuing a spent
budget (it runs the paused turn).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, TypeAlias, cast

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import Field
from sse_starlette import EventSourceResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ops_access import can
from ops_agents.activities.overrides import limits_for, parse, resolve
from ops_contracts.chat import BudgetAnswer, ChatThreadInput, SendInput
from ops_identity import CurrentPrincipal
from ops_identity.fastapi import Tx
from ops_service_kit.errors import (
    Conflict,
    Forbidden,
    NotFound,
    ServiceUnavailable,
    Unauthorized,
    Unprocessable,
    ValidationFailed,
)
from ops_service_kit.http import Envelope, In, Out
from ops_service_kit.ids import new_id, now_iso
from ops_store import isolation

from ...store.widget_deployments import WidgetDeployments
from ...store.widget_keys import WidgetKeys
from ..agent_registry import live_agent, pinned_definition, registry
from ..auth import Principal, caller_of, principal, reader_of, require_builder
from ..chat_threads import chat_row, update_meta
from ..deps import Runtime, runtime
from ..envelope import ok
from ..runs import graph_store
from ..widget_sessions import (
    SESSION_TTL_S,
    RateLimit,
    WidgetSession,
    allowed,
    claimed_tenant,
    mint_session,
    normal_origin,
    read_session,
)
from . import chat as chat_routes
from . import chat_settings as chat_settings_routes

Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040
Deployments: TypeAlias = Annotated[Principal, Depends(reader_of("deployments"))]  # noqa: UP040

deployments_router = APIRouter(prefix="/v1/widget-deployments", tags=["widget"], dependencies=[Depends(principal)])
# The bank's server mints sessions here with a deployment's mint key, not a platform token, so no principal is read.
mint_router = APIRouter(prefix="/v1/widget-deployments", tags=["widget"])
widget_router = APIRouter(prefix="/v1/widget/{deployment_id}", tags=["widget"])
# Read by the embed app's server before a page has a session; it carries nothing a page could act with.
config_router = APIRouter(prefix="/v1/widget/{deployment_id}", tags=["widget"])
bundle_router = APIRouter(tags=["widget"])
LOADER = Path(__file__).resolve().parents[2] / "static" / "ops-chat-loader.js"


@bundle_router.get("/widget/v1.js", include_in_schema=False)
async def retired_bundle() -> Response:
    """The first widget script, retired: pages load `/embed/v1.js` and call `OpsChat.init`. Gone, not
    redirected: the two scripts take different tags (`data-token` against `OpsChat.init`), so an old tag served the new
    script would draw nothing and say nothing."""
    return Response(
        "/* Retired. Load /embed/v1.js and call OpsChat.init; see the embed dialog in the console. */\n",
        status_code=410,
        media_type="text/javascript",
    )


@bundle_router.get("/embed/v1.js", include_in_schema=False)
async def loader() -> FileResponse:
    """The embedded chat's loader: launcher, frame and the session hand-over. Public: it holds no key; the chat
    itself is the embed app's page under `/embed/{deployment}` on the same host."""
    return FileResponse(LOADER, media_type="text/javascript", headers={"Cache-Control": "public, max-age=300"})


limits = RateLimit()


class WidgetDeploymentInput(In):
    name: str = Field(min_length=1, max_length=200)
    agent_id: str
    origins: list[str] = Field(min_length=1, max_length=20)


class SessionInput(In):
    """A session the bank's server mints for one person on one page."""

    email: str = Field(min_length=3, max_length=320)
    name: str = Field(min_length=1, max_length=200)
    origin: str


class WidgetDeploymentOut(Out):
    id: str
    name: str
    agent_id: str
    # None: the deployment follows the agent's newest published version.
    agent_version: int | None
    origins: list[str]
    paused: bool
    retired_at: str | None
    team_id: str
    created_by: str
    created_at: str
    updated_at: str


class WidgetDeploymentUsageOut(WidgetDeploymentOut):
    """A row of the list: the deployment and its use over the last USAGE_DAYS days."""

    # Named as it is: the camelCase alias would read `conversations7D`.
    conversations7d: int = Field(alias="conversations7d")
    last_used_at: str | None
    active_keys: int


class MintKeyOut(Out):
    id: str
    name: str
    created_by: str
    created_at: str
    last_used_at: str | None
    revoked_at: str | None
    expires_at: str | None


class MintKeyCreatedOut(Out):
    key: MintKeyOut
    # `wk.<tenant>.<key id>.<secret>`: shown once, stored hashed.
    secret: str


class MintKeyRevokedOut(Out):
    id: str
    revoked: bool


class KeyAuditOut(Out):
    key_id: str
    action: str
    actor: str
    at: str


class SessionOut(Out):
    session: str
    expires_in: int


class PageSessionOut(SessionOut):
    agent_name: str
    deployment_name: str


class WidgetConfigOut(Out):
    agent_name: str
    deployment_name: str
    allowed_origins: list[str]
    paused: bool
    retired: bool
    suggestions: list[str]


def _store(rt: Runtime) -> WidgetDeployments:
    return WidgetDeployments(graph_store(rt).engine)


USAGE_DAYS = 7


def _wire(reply: Out) -> dict[str, object]:
    return reply.model_dump(mode="json", by_alias=True)


def _view(row: dict[str, Any]) -> WidgetDeploymentOut:
    return WidgetDeploymentOut(
        id=row["id"],
        name=row["name"],
        agent_id=row["agent_id"],
        agent_version=row["agent_version"],
        origins=list(row["origins"]),
        paused=bool(row["paused"]),
        retired_at=row.get("retired_at"),
        team_id=row["team_id"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _published(rt: Runtime, agent_id: str) -> tuple[dict[str, Any], int]:
    row = await registry(rt).row(agent_id)
    if row["published_version"] is None or row["paused"]:
        raise Unprocessable(
            "Publish the agent, and resume it if it is paused, before deploying it as a widget.", code="not_published"
        )
    return row, int(row["published_version"])


async def served_version(rt: Runtime, row: dict[str, Any]) -> int:
    """The agent version a deployment serves now: its pin, or on Latest the agent's newest published version."""
    if row["agent_version"] is not None:
        return int(row["agent_version"])
    return (await _published(rt, str(row["agent_id"])))[1]


async def make_deployment(rt: Runtime, me: Principal, body: WidgetDeploymentInput) -> dict[str, Any]:
    """A chat channel: the agent pinned at its published version, on exact origins, in the caller's team. The one
    create both `POST /v1/channels` and its deprecated alias here use."""
    agent_row, version = await _published(rt, body.agent_id)
    team = me.team_id or str(agent_row["team_id"])
    require_builder(me, area="deployments", team_id=team, action="create", what=WHAT)
    if agent_row["team_id"] and agent_row["team_id"] != team:
        raise Forbidden("Deploy an agent from the team that owns it.", code="team_forbidden")
    now = now_iso()
    row = {
        "id": new_id("wd"),
        "team_id": team,
        "name": body.name.strip(),
        "agent_id": body.agent_id,
        "agent_version": version,
        "origins": sorted({normal_origin(o) for o in body.origins}),
        "paused": False,
        "created_by": me.email,
        "created_at": now,
        "updated_at": now,
    }
    await _store(rt).add(row)
    return row


# Deprecated: `POST /v1/channels` with `type: chat` creates and `GET /v1/channels?type=chat&agentId=` lists,
# with these fields under `embed`. Kept until the console's adapter moves, then removed.
@deployments_router.post("", status_code=201, deprecated=True, response_model=Envelope[WidgetDeploymentOut])
async def create_deployment(rt: Rt, me: Me, _: Tx, body: WidgetDeploymentInput) -> JSONResponse:
    row = await make_deployment(rt, me, body)
    return ok(_wire(_view(row)), status=201)


@deployments_router.get("", deprecated=True, response_model=Envelope[list[WidgetDeploymentUsageOut]])
async def list_deployments(
    rt: Rt, me: Deployments, _: Tx, agent_id: Annotated[str | None, Query(alias="agentId")] = None
) -> JSONResponse:
    """The team's widget deployments, newest first; `agentId` keeps one agent's. Unpaged: it goes when the console's
    adapter moves to `GET /v1/channels?type=chat&agentId=`, which pages."""
    rows = await _store(rt).for_team(me.team_id)
    rows = [r for r in rows if agent_id is None or r["agent_id"] == agent_id]
    return ok([_wire(r) for r in await _usage(rt, rows)])


async def _usage(rt: Runtime, rows: list[dict[str, Any]]) -> list[WidgetDeploymentUsageOut]:
    """Each deployment with its conversations started in the last USAGE_DAYS days, when one last changed, and its
    unrevoked keys, each counted in the database. A conversation counts for the deployment it was started on, in its
    team."""
    team_of = {str(r["id"]): str(r["team_id"]) for r in rows}
    since = (datetime.now(UTC) - timedelta(days=USAGE_DAYS)).isoformat()
    used = await graph_store(rt).deployment_usage(team_of, since)
    keys = await _key_store(rt).active_counts(list(team_of))
    return [
        WidgetDeploymentUsageOut(
            **_view(r).model_dump(),
            conversations7d=used.get(str(r["id"]), (0, None))[0],
            last_used_at=used.get(str(r["id"]), (0, None))[1],
            active_keys=keys.get(str(r["id"]), 0),
        )
        for r in rows
    ]


async def _owned(rt: Runtime, me: Principal, deployment_id: str) -> dict[str, Any]:
    row = await _store(rt).get(deployment_id)
    if row is None or row["team_id"] not in me.team_ids:
        raise NotFound("Widget deployment")
    return row


class MintKeyInput(In):
    name: str = Field(min_length=1, max_length=200)
    # As platform keys: every mint key ends; 90 days unless the builder picks another span up to a year.
    expires_in_days: int = Field(default=90, ge=1, le=365)


WHAT = "this widget deployment"
# The isolation context of a widget request: its tenant and team come from the deployment its key or session names.
WIDGET = "widget"
# A mint key, a widget session or the embed app's config request names a tenant and a deployment but no team, and a
# team scope with no team reads no team's rows; the deployment is read across the tenant's teams, then its team entered.
WIDGET_LOOKUP = "widget_lookup"


def _key_store(rt: Runtime) -> WidgetKeys:
    return WidgetKeys(graph_store(rt).engine)


async def _named_deployment(rt: Runtime, deployment_id: str) -> dict[str, Any] | None:
    """The deployment a widget credential names, in its tenant, whichever team owns it."""
    with isolation.tenant_wide(WIDGET_LOOKUP):
        return await _store(rt).get(deployment_id)


def _key_view(k: dict[str, Any]) -> MintKeyOut:
    return MintKeyOut(
        id=k["id"],
        name=k["name"],
        created_by=k["created_by"],
        created_at=k["created_at"],
        last_used_at=k["last_used_at"],
        revoked_at=k["revoked_at"],
        expires_at=k.get("expires_at"),
    )


@deployments_router.post("/{deployment_id}/keys", status_code=201, response_model=Envelope[MintKeyCreatedOut])
async def create_mint_key(rt: Rt, me: Me, _: Tx, deployment_id: str, body: MintKeyInput) -> JSONResponse:
    """A key the bank's server mints this deployment's sessions with; its secret is shown once and stored hashed."""
    row = await _owned(rt, me, deployment_id)
    require_builder(me, area="deployments", team_id=str(row["team_id"]), action="edit", what=WHAT)
    key_id, secret = new_id("wkk"), secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    record = {
        "id": key_id,
        "deployment_id": deployment_id,
        "name": body.name.strip(),
        "secret_hash": hashlib.sha256(secret.encode()).hexdigest(),
        "created_by": me.email,
        "created_at": now.isoformat(),
        "last_used_at": None,
        "revoked_at": None,
        "expires_at": (now + timedelta(days=body.expires_in_days)).isoformat(),
    }
    await _key_store(rt).add(record)
    made = MintKeyCreatedOut(key=_key_view(record), secret=f"wk.{row['tenant_id']}.{key_id}.{secret}")
    return ok(_wire(made), status=201)


@deployments_router.get("/{deployment_id}/keys", response_model=Envelope[list[MintKeyOut]])
async def list_mint_keys(rt: Rt, me: Deployments, _: Tx, deployment_id: str) -> JSONResponse:
    """A deployment's keys, newest first, unpaged: a deployment holds a handful."""
    await _owned(rt, me, deployment_id)
    return ok([_wire(_key_view(k)) for k in await _key_store(rt).for_deployment(deployment_id)])


@deployments_router.post("/{deployment_id}/keys/{key_id}/revoke", response_model=Envelope[MintKeyRevokedOut])
async def revoke_mint_key(rt: Rt, me: Me, _: Tx, deployment_id: str, key_id: str) -> JSONResponse:
    row = await _owned(rt, me, deployment_id)
    require_builder(me, area="deployments", team_id=str(row["team_id"]), action="edit", what=WHAT)
    if not await _key_store(rt).revoke(deployment_id, key_id, now_iso(), me.email):
        raise NotFound("Mint key")
    return ok(_wire(MintKeyRevokedOut(id=key_id, revoked=True)))


@deployments_router.post("/{deployment_id}/preview-session", status_code=201, response_model=Envelope[SessionOut])
async def preview_session(rt: Rt, me: Me, caller: CurrentPrincipal, _: Tx, deployment_id: str) -> JSONResponse:
    """The console's "Preview as a person": a session for the signed-in person who may edit this deployment, bound to
    the console's own origin (`console_url`), so it serves the console's preview frame and no bank page. Recorded on the
    deployment's key audit. An API key never previews: it would hand a person's chat to a server."""
    if caller.auth_method == "api_key":
        raise Forbidden("A person previews from the console, signed in.", code="api_key_refused")
    row = await _owned(rt, me, deployment_id)
    require_builder(me, area="deployments", team_id=str(row["team_id"]), action="edit", what=WHAT)
    _refuse_stopped(row)
    if not rt.settings.console_url:
        raise ServiceUnavailable("Preview needs the console's address (OPS_CONSOLE_URL) set on agents-service.")
    await _key_store(rt).previewed(deployment_id, me.email, now_iso())
    session = mint_session(rt, row, normal_origin(rt.settings.console_url), me)
    return ok(_wire(SessionOut(session=session, expires_in=SESSION_TTL_S)), status=201)


@deployments_router.get("/{deployment_id}/keys/audit", response_model=Envelope[list[KeyAuditOut]])
async def mint_key_audit(rt: Rt, me: Deployments, _: Tx, deployment_id: str) -> JSONResponse:
    """Who created, revoked and previewed with this deployment's mint keys, newest first; unpaged, as the keys."""
    await _owned(rt, me, deployment_id)
    rows = await _key_store(rt).audit(deployment_id)
    return ok([_wire(KeyAuditOut(key_id=r["key_id"], action=r["action"], actor=r["actor"], at=r["at"])) for r in rows])


def _key_refused() -> Forbidden:
    return Forbidden(
        "Mint widget sessions from the bank's server with the deployment's mint key (Widgets, Mint keys).",
        code="widget_key_required",
    )


@dataclass(frozen=True)
class MintKey:
    key_id: str
    deployment: dict[str, Any]


async def mint_key_caller(rt: Rt, deployment_id: str, authorization: Annotated[str | None, Header()] = None) -> MintKey:
    """How the bank's server authenticates a mint: the deployment's own mint key, `wk.<tenant>.<key id>.<secret>`
    (check_standards rule 5 counts it as an auth dependency). A team API key or a person's token is refused, since
    either can do far more than vouch for one person in one chat."""
    scheme, _, token = (authorization or "").partition(" ")
    parts = token.split(".") if scheme.lower() == "bearer" else []
    if len(parts) != 4 or parts[0] != "wk":
        raise _key_refused()
    _, tenant, key_id, secret = parts
    # The key is looked up in the tenant its text names; until it is checked the context names no team.
    isolation.enter(tenant, None, kind=WIDGET)
    key = await _key_store(rt).get(key_id)
    digest = hashlib.sha256(secret.encode()).hexdigest()
    if key is None or key["revoked_at"] is not None or not hmac.compare_digest(digest, str(key["secret_hash"])):
        raise Unauthorized("That mint key is not valid or was revoked.", code="widget_key_invalid")
    if key["expires_at"] and str(key["expires_at"]) <= datetime.now(UTC).isoformat():
        raise Unauthorized("That mint key has expired; create a new one.", code="widget_key_expired")
    if key["deployment_id"] != deployment_id:
        raise Forbidden("That mint key is for another widget deployment.", code="widget_key_other_deployment")
    row = await _named_deployment(rt, deployment_id)
    if row is None:
        raise NotFound("Widget deployment")
    isolation.enter(tenant, str(row["team_id"]), kind=WIDGET)
    return MintKey(key_id, row)


Minter: TypeAlias = Annotated[MintKey, Depends(mint_key_caller)]  # noqa: UP040


@mint_router.post("/{deployment_id}/sessions", status_code=201, response_model=Envelope[SessionOut])
async def server_session(rt: Rt, _: Tx, minter: Minter, body: SessionInput) -> JSONResponse:
    """The bank's server mints a session for one person and hands it to the page. The key itself never reaches the
    page. The key check, the deployment read and the key's last use are one transaction."""
    row = minter.deployment
    _refuse_stopped(row)
    origin = allowed(row, body.origin)
    person = Principal(
        name=body.name, email=body.email, team_id=str(row["team_id"]), tenant_id=str(row["tenant_id"]), sub=body.email
    )
    await _key_store(rt).used(minter.key_id, now_iso())
    return ok(_wire(SessionOut(session=mint_session(rt, row, origin, person), expires_in=SESSION_TTL_S)), status=201)


# ── the page ──


def _claimed_origin(token: str) -> str | None:
    """The page origin a session names, unverified; `read_session` then checks the session against it."""
    try:
        part = token.split(".")[1]
        claims: object = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError):
        return None
    origin = cast(dict[str, object], claims).get("origin") if isinstance(claims, dict) else None
    return origin if isinstance(origin, str) and origin else None


def _page_origin(request: Request, session_token: str | None, embed_origins: list[str]) -> str | None:
    """The page a request speaks for. The embed app's iframe sends its own origin, which `Settings.embed_origins`
    lists; such a request speaks for the bank page its session was minted for. The list is configuration, so
    no Host or X-Forwarded-Host header can make a page's origin count as the embed app's."""
    origin = request.headers.get("origin")
    if not session_token or not embed_origins:
        return origin
    if origin is None:
        # A same-origin GET from the embed app carries no Origin; the browser's Sec-Fetch-Site, which no page script
        # can set, says it is one.
        return _claimed_origin(session_token) if request.headers.get("sec-fetch-site") == "same-origin" else None
    if normal_origin(origin) in {normal_origin(o) for o in embed_origins}:
        return _claimed_origin(session_token)
    return origin


def _listed(
    request: Request,
    row: dict[str, Any] | None,
    session_token: str | None = None,
    embed_origins: list[str] | None = None,
    console_origin: str | None = None,
) -> dict[str, Any]:
    """The deployment with the page's origin on its list. The origin is marked allowed before anything else is checked,
    so an error that follows (an ended session, a pause) still reaches the page; an unlisted origin reads nothing. The
    team every widget request acts in is the deployment's. A session on the console's own origin (a preview, which only
    an editor mints) is allowed too; `read_session` then checks it was minted for that origin."""
    if row is None:
        raise NotFound("Widget")
    origin = _page_origin(request, session_token, embed_origins or [])
    previewing = bool(session_token and console_origin and origin and normal_origin(origin) == console_origin)
    request.state.widget_origin = console_origin if previewing else allowed(row, origin)
    isolation.enter(isolation.tenant(), str(row["team_id"]), kind=WIDGET)
    _refuse_stopped(row)
    return row


def _refuse_stopped(row: dict[str, Any]) -> None:
    """No session or turn for an embed that is retired (for good) or paused (until resumed)."""
    if row.get("retired_at"):
        raise Conflict("This chat has been retired by the team that ran it.", code="widget_retired")
    if row["paused"]:
        raise Conflict("This widget is paused; ask the team that runs it.", code="widget_paused")


SessionHeader: TypeAlias = Annotated[str | None, Header(alias="X-Widget-Session")]  # noqa: UP040


async def listed_deployment(
    rt: Rt, request: Request, deployment_id: str, session_token: SessionHeader = None
) -> dict[str, Any]:
    """The deployment a page route names, in the tenant its session names (`claimed_tenant`); a session for another
    tenant finds no deployment."""
    tenant = claimed_tenant(session_token)
    if tenant is None:
        raise Unauthorized("This widget has no session; it starts one when it loads.")
    isolation.enter(tenant, None, kind=WIDGET)
    console = normal_origin(rt.settings.console_url) if rt.settings.console_url else None
    row = await _named_deployment(rt, deployment_id)
    return _listed(request, row, session_token, rt.settings.embed_origins, console)


Listed: TypeAlias = Annotated[dict[str, Any], Depends(listed_deployment)]  # noqa: UP040


@dataclass(frozen=True)
class WidgetCaller:
    session: WidgetSession
    deployment: dict[str, Any]


async def widget_caller(rt: Rt, request: Request, row: Listed, session_token: SessionHeader = None) -> WidgetCaller:
    """How every page route after the session exchange authenticates: the `X-Widget-Session` the page holds, minted for
    this deployment and the page's origin (check_standards rule 5 counts it as an auth dependency)."""
    return WidgetCaller(
        read_session(rt, session_token, row, _page_origin(request, session_token, rt.settings.embed_origins)), row
    )


Caller: TypeAlias = Annotated[WidgetCaller, Depends(widget_caller)]  # noqa: UP040


@widget_router.post("/session", status_code=201, response_model=Envelope[PageSessionOut])
async def page_session(
    rt: Rt, me: Me, caller: CurrentPrincipal, _: Tx, request: Request, deployment_id: str
) -> JSONResponse:
    """The page exchanges the person's SSO token (the `Authorization` header) for a widget session on this origin. Only
    a person of the deployment's team, in its tenant: anyone else is refused, as for chat. An API key never
    mints here; the bank's server uses `/v1/widget-deployments/{id}/sessions`."""
    if caller.auth_method == "api_key":
        raise Forbidden("A page signs the person in; servers mint with /sessions.", code="api_key_refused")
    # The person's token set their tenant; a deployment of another tenant is not found.
    row = _listed(request, await _store(rt).get(deployment_id))
    # chat.run in the deployment's team, from whichever team the page's sign-in selected.
    can(
        caller_of(me),
        "chat",
        "run",
        team=str(row["team_id"]),
        what="this widget",
        from_any_team=True,
        code="team_forbidden",
    )
    agent = await pinned_definition(rt, str(row["agent_id"]), await served_version(rt, row))
    body = PageSessionOut(
        session=mint_session(rt, row, str(request.state.widget_origin), me),
        expires_in=SESSION_TTL_S,
        agent_name=agent.name if agent else str(row["agent_id"]),
        deployment_name=row["name"],
    )
    return ok(_wire(body), status=201)


async def _widget_thread(rt: Runtime, session: WidgetSession, thread_id: str) -> None:
    row = await chat_row(rt, thread_id, session.principal())
    meta = cast(dict[str, Any], row["meta"] or {}) if row is not None else {}
    if row is None or meta.get("deploymentId") != session.deployment_id:
        raise NotFound("Conversation")


@widget_router.post("/threads", status_code=201)
async def create_thread(rt: Rt, caller: Caller) -> JSONResponse:
    """No request transaction: chat's start asks kb-service for the names of the agent's knowledge bases when it has
    any, and no connection is held while it answers. Each store call is its own short transaction."""
    session, row = caller.session, caller.deployment
    made = await chat_routes.create_thread(
        rt=rt, me=session.principal(), body=ChatThreadInput(agent_id=str(row["agent_id"]), kb_ids=[])
    )
    thread_id = json.loads(bytes(made.body))["data"]["id"]
    # A conversation stays on the version it started on, also when the deployment follows Latest.
    version = await served_version(rt, row)
    await update_meta(rt, thread_id, deploymentId=row["id"], agentVersion=version, channel="widget")
    await graph_store(rt).set_deployment(thread_id, str(row["id"]))
    view = await chat_routes.get_thread(rt=rt, me=session.principal(), thread_id=thread_id)
    return JSONResponse(json.loads(bytes(view.body)), status_code=201)


@widget_router.get("/threads/{thread_id}")
async def get_thread(rt: Rt, _: Tx, caller: Caller, thread_id: str) -> JSONResponse:
    """The page's own conversation, read in one transaction with its session's deployment."""
    await _widget_thread(rt, caller.session, thread_id)
    return await chat_routes.get_thread(rt=rt, me=caller.session.principal(), thread_id=thread_id)


@widget_router.post("/threads/{thread_id}/messages", response_model=None)
async def send(rt: Rt, caller: Caller, deployment_id: str, thread_id: str, body: SendInput) -> EventSourceResponse:
    """A model turn, streamed: no request transaction, so none is held while the model answers or the stream runs."""
    session, row = caller.session, caller.deployment
    await _widget_thread(rt, session, thread_id)
    limits.check(deployment_id, session.email)
    if body.overrides is not None:
        # A page is a public caller: only what the agent lets a public key change (overrides.resolve, caller class).
        agent = await pinned_definition(rt, str(row["agent_id"]), await served_version(rt, row)) or await live_agent(
            rt, str(row["agent_id"])
        )
        if agent is None:
            raise Unprocessable("This widget's agent is no longer live.")
        resolve(
            limits_for(agent, rt.settings.model_alias),
            agent.default_kb_ids,
            turn=parse(body.overrides, "turn"),
            caller="public_key",
        )
    if body.regenerate or body.edit:
        raise ValidationFailed("A widget sends new messages only.")
    return await chat_routes.send(rt=rt, me=session.principal(), thread_id=thread_id, body=body)


@widget_router.post("/threads/{thread_id}/budget")
async def budget(rt: Rt, caller: Caller, thread_id: str, body: BudgetAnswer) -> JSONResponse:
    """Continue a spent conversation budget, as the conversation's owner; raising is chat.manage, which no widget
    session holds. No request transaction: continuing runs the paused turn, a model call."""
    await _widget_thread(rt, caller.session, thread_id)
    # Raising is chat.manage; a widget session holds no role, so `can` refuses it as for any non-admin.
    return await chat_settings_routes.budget(rt=rt, me=caller.session.principal(), thread_id=thread_id, body=body)


TenantQuery: TypeAlias = Annotated[str, Query(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")]  # noqa: UP040


@config_router.get("/config", response_model=Envelope[WidgetConfigOut])
async def public_config(
    rt: Rt,
    _: Tx,
    request: Request,
    deployment_id: str,
    tenant: TenantQuery,
    authorization: Annotated[str | None, Header()] = None,
) -> JSONResponse:
    """What the embed app needs before any session exists: the agent's name and starter questions, whether the
    widget is paused, and the origins it builds `Content-Security-Policy: frame-ancestors` from. It answers a
    request whose Origin the deployment lists (the embed app forwards the framing page's), the console's own origin
    (its preview), or a server holding this deployment's mint key; anything else is 403. It names no team or tenant,
    and an unknown deployment, or one in another tenant, is 404."""
    isolation.enter(tenant, None, kind=WIDGET)
    row = await _named_deployment(rt, deployment_id)
    if row is None:
        raise NotFound("Widget")
    origin = request.headers.get("origin")
    console = normal_origin(rt.settings.console_url) if rt.settings.console_url else None
    if authorization:
        await mint_key_caller(rt, deployment_id, authorization)
    elif console and origin and normal_origin(origin) == console:
        # The console's preview frame reads the config before its preview session exists; the session it then needs
        # is minted only for an editor of the deployment (preview_session).
        request.state.widget_origin = console
    else:
        request.state.widget_origin = allowed(row, origin)
    agent = await pinned_definition(rt, str(row["agent_id"]), await served_version(rt, row))
    body = WidgetConfigOut(
        agent_name=agent.name if agent else str(row["agent_id"]),
        deployment_name=row["name"],
        allowed_origins=list(row["origins"]),
        # A retired embed reads as paused to the embed app, which then shows it offline, and says why.
        paused=bool(row["paused"]) or bool(row.get("retired_at")),
        retired=bool(row.get("retired_at")),
        suggestions=list(agent.suggestions) if agent else [],
    )
    return ok(_wire(body))


class WidgetCors:
    """CORS for `/v1/widget/*`, outside the console's CORS middleware. A preflight carries no data and no credentials,
    so it is answered for any origin; an actual response carries `Access-Control-Allow-Origin` only when the route set
    the request's origin as allowed for the deployment (`request.state.widget_origin`), so a browser on any other page
    reads nothing. The routes refuse other origins themselves."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not str(scope["path"]).startswith("/v1/widget/"):
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        origin = headers.get("origin")
        if scope["method"] == "OPTIONS" and origin and "access-control-request-method" in headers:
            response = Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": origin,
                    "Access-Control-Allow-Methods": "GET, POST",
                    "Access-Control-Allow-Headers": "Authorization, Content-Type, X-Widget-Session, Accept",
                    "Access-Control-Max-Age": "600",
                    "Vary": "Origin",
                },
            )
            await response(scope, receive, send)
            return

        async def with_cors(message: Message) -> None:
            if message["type"] == "http.response.start":
                ok_origin = scope.get("state", {}).get("widget_origin")
                # The console's origin is on the app's CORS list too, so that layer may have named it already; a
                # second copy makes the browser refuse the response.
                named = any(k.lower() == b"access-control-allow-origin" for k, _ in message.get("headers", []))
                if ok_origin and not named and ok_origin == (origin or "").rstrip("/").lower():
                    message["headers"] = [
                        *message.get("headers", []),
                        (b"access-control-allow-origin", ok_origin.encode()),
                        (b"vary", b"Origin"),
                    ]
            await send(message)

        await self.app(scope, receive, with_cors)
