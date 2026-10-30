"""Hosted forms (c-535): a workflow's start form shared as a page of its own.

A builder shares a live workflow whose Request trigger declares its inputs, as a signed link that expires or as a
members-only page. The link's token is `fk.<tenant>.<team>.<form>.<secret>`: a submission enters the tenant and team
it names and reads the form by id there, so no read crosses teams, then checks the URL's slug against the form and
the secret against its hash. Before sign-in the page shows the form's title, description and fields only.

Submissions are limited twice: 10 a minute per client address, the address read from the raw X-Forwarded-For header
past the deploy's trusted proxies (never from `request.client`, which uvicorn already rewrites for a 127.0.0.1 peer),
and the form's daily cap, counted with the form's row locked (`FormLinks.reserve`).
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal, TypeAlias, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ops_engine import default_registry
from ops_engine.node_types import start_form
from ops_engine.store import DefinitionStore, RunStore
from ops_files_client import FilesClient, FilesRefused
from ops_service_kit.errors import (
    Conflict,
    Forbidden,
    NotFound,
    ServiceUnavailable,
    TooManyRequests,
    Unauthorized,
    Unprocessable,
)
from ops_service_kit.http import Envelope
from ops_store import isolation

from ...store.engine import EngineTransactions
from ...store.form_links import FormLinks, source_of
from ...store.tenancy import current_tenant
from ...store.trigger_events import TriggerEvent, TriggerEvents
from ..auth import Principal, principal, require_builder, started_by
from ..deps import Runtime, runtime
from ..engine_runs import live_version, start_run
from ..envelope import ok
from ..schemas import Out
from ..widget_sessions import RateLimit

router = APIRouter(tags=["forms"])
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040

# The isolation context of a link submission: the tenant and team its signed token names.
FORM = "form"
TOKEN = re.compile(r"^fk\.(?P<tenant>.+)\.(?P<team>[^.]+)\.(?P<form>[^.]+)\.(?P<secret>[A-Za-z0-9_-]+)$")
PER_MINUTE = 10
DEFAULT_DAYS = 30
DEFAULT_CAP = 200
# How a link run is created: read by actors as a trigger named by the form's title.
FORM_TRIGGER = "trigger:form:"
HOSTED_FORM = "start:hosted_form"
EXPIRED = "This link has expired or was replaced. Ask whoever sent it to you for a new one."
limits = RateLimit()


class FormIn(BaseModel):
    mode: Literal["link", "members"] = "link"
    expires_in_days: int = Field(default=DEFAULT_DAYS, ge=1, le=90, alias="expiresInDays")
    daily_cap: int = Field(default=DEFAULT_CAP, ge=1, le=10_000, alias="dailyCap")
    title: str | None = Field(default=None, max_length=200)
    description: str = Field(default="", max_length=1000)
    after_text: str = Field(default="", max_length=1000, alias="afterText")


class FormPatch(BaseModel):
    paused: bool | None = None
    daily_cap: int | None = Field(default=None, ge=1, le=10_000, alias="dailyCap")
    after_text: str | None = Field(default=None, max_length=1000, alias="afterText")


class SubmitIn(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict[str, Any])


class FormView(Out):
    id: str
    workflow_id: str
    slug: str
    mode: Literal["link", "members"]
    title: str
    description: str
    after_text: str
    expires_at: str
    daily_cap: int
    paused: bool
    # The page's path; with the link's token only when it was just made (create or Rotate).
    url: str
    token: str | None = None


class FormFields(Out):
    schema_: dict[str, Any] = Field(alias="schema")
    takes_files: bool | None = None


class PublicForm(Out):
    """All a person sees before sign-in: no team, no workflow id."""

    title: str
    description: str
    form: FormFields
    after_text: str


class Received(Out):
    received: bool
    # The run a members-only submission started; a link submission never sees its run.
    run_id: str | None = None


class UploadedFile(Out):
    file_id: str
    name: str


def _links(rt: Runtime) -> FormLinks:
    return FormLinks(rt.db)


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _token(tenant: str, team: str, form_id: str) -> tuple[str, str]:
    secret = secrets.token_urlsafe(24)
    return f"fk.{tenant}.{team}.{form_id}.{secret}", _hash(secret)


def _slug(title: str) -> str:
    words = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "form"
    return f"{words}-{secrets.token_hex(3)}"


def _view(row: dict[str, Any], token: str | None = None) -> dict[str, Any]:
    out = {
        "id": row["id"],
        "workflowId": row["workflow_id"],
        "slug": row["slug"],
        "mode": row["mode"],
        "title": row["title"],
        "description": row["description"],
        "afterText": row["after_text"],
        "expiresAt": row["expires_at"],
        "dailyCap": row["daily_cap"],
        "paused": bool(row["paused"]),
        "url": f"/f/{row['slug']}" + (f"?t={token}" if token else ""),
    }
    return out | ({"token": token} if token else {})


def _inputs(stored: dict[str, Any]) -> dict[str, Any]:
    """The live version's start form, when its trigger declares inputs a person can fill."""
    form = start_form(stored["definition"], default_registry())
    if form is None or form.get("kind") != "form" or not cast(dict[str, Any], form["schema"]).get("properties"):
        raise Conflict(
            "This workflow's Request trigger has no input form. Add the fields people fill in to the trigger first.",
            code="form_needs_inputs",
        )
    return form


def _store(rt: Runtime) -> DefinitionStore:
    return DefinitionStore(EngineTransactions(rt.db))


@router.post("/v1/workflows/{workflow_id}/forms", status_code=201, response_model=Envelope[FormView])
async def create_form(rt: Rt, me: Me, workflow_id: str, body: FormIn) -> JSONResponse:
    """Shares the workflow's live start form as a page: a signed link that expires, or a members-only page. The token
    is shown once, here and on Rotate."""
    stored = await live_version(_store(rt), workflow_id, None, team=me.team_id)
    team = str(stored.get("team_id") or me.team_id)
    require_builder(me, area="workflows", team_id=team, action="edit", what=f"workflow {workflow_id}")
    _inputs(stored)
    title = body.title or str(stored.get("name") or workflow_id)
    expires = (datetime.now(UTC) + timedelta(days=body.expires_in_days)).isoformat()
    links = _links(rt)
    row = await links.create(
        team_id=me.team_id,
        workflow_id=workflow_id,
        slug=_slug(title),
        mode=body.mode,
        daily_cap=body.daily_cap,
        expires_at=expires,
        created_by=started_by(me),
        title=title,
        description=body.description,
        after_text=body.after_text,
    )
    token, hashed = _token(current_tenant(), me.team_id, str(row["id"]))
    row = await links.update(str(row["id"]), token_hash=hashed) or row
    return ok(_view(row, token if body.mode == "link" else None), 201)


@router.get("/v1/workflows/{workflow_id}/forms", response_model=Envelope[list[FormView]])
async def workflow_forms(rt: Rt, me: Me, workflow_id: str) -> JSONResponse:
    return ok([_view(r) for r in await _links(rt).of_workflow(workflow_id)])


async def _own(rt: Runtime, me: Principal, form_id: str) -> dict[str, Any]:
    row = await _links(rt).get(form_id)
    if row is None:
        raise NotFound(f"Form {form_id}")
    require_builder(me, area="workflows", team_id=str(row["team_id"]), action="edit", what=f"form {form_id}")
    return row


@router.post("/v1/forms/{form_id}/rotate", response_model=Envelope[FormView])
async def rotate_form(rt: Rt, me: Me, form_id: str) -> JSONResponse:
    """A new link for the form; the old one stops working at once."""
    row = await _own(rt, me, form_id)
    token, hashed = _token(current_tenant(), str(row["team_id"]), form_id)
    now = datetime.now(UTC).isoformat()
    row = await _links(rt).update(form_id, token_hash=hashed, rotated_at=now) or row
    return ok(_view(row, token))


@router.patch("/v1/forms/{form_id}", response_model=Envelope[FormView])
async def update_form(rt: Rt, me: Me, form_id: str, body: FormPatch) -> JSONResponse:
    await _own(rt, me, form_id)
    changes = body.model_dump(exclude_none=True)
    row = await _links(rt).update(form_id, **changes) if changes else await _links(rt).get(form_id)
    assert row is not None
    return ok(_view(row))


def _address(request: Request, trusted: list[str]) -> str:
    """The client's address: the right-most X-Forwarded-For entry outside the trusted proxies, read from the raw
    header; the peer only when there is no header. A left-hand entry a client wrote itself is never reached."""
    nets = [ipaddress.ip_network(n, strict=False) for n in trusted]

    def inside(raw: str) -> bool:
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            return False
        return any(ip in n for n in nets)

    chain = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    for hop in reversed(chain):
        if not inside(hop):
            return hop
    return chain[0] if chain else (request.client.host if request.client else "unknown")


def _opened(token: str, slug: str) -> tuple[str, str, str, str]:
    """The tenant, team, form and secret a link's token names; 401 when it is not one of ours."""
    m = TOKEN.match(token or "")
    if m is None:
        raise Unauthorized(EXPIRED, code="form_link_expired")
    return m["tenant"], m["team"], m["form"], m["secret"]


async def _linked(rt: Runtime, slug: str, token: str) -> dict[str, Any]:
    """The form a link opens, inside the tenant and team its token names: 404 for a token made for another form, 401
    for an expired, rotated or paused one."""
    tenant, team, form_id, secret = _opened(token, slug)
    isolation.enter(tenant, team, kind=FORM)
    row = await _links(rt).get(form_id)
    if row is None or row["slug"] != slug:
        raise NotFound("Form")
    fresh = hmac.compare_digest(_hash(secret), str(row["token_hash"]))
    if not fresh or row["mode"] != "link" or row["paused"] or str(row["expires_at"]) <= datetime.now(UTC).isoformat():
        raise Unauthorized(EXPIRED, code="form_link_expired")
    return row


def _public(row: dict[str, Any], form: dict[str, Any]) -> dict[str, Any]:
    """What a person sees before sign-in: the form's title, description and fields, and what is said after."""
    shown = {k: form[k] for k in ("schema", "takesFiles") if k in form}
    return {"title": row["title"], "description": row["description"], "form": shown, "afterText": row["after_text"]}


@router.get("/v1/forms/public/{slug}", response_model=Envelope[PublicForm])
async def public_form(rt: Rt, slug: str, t: Annotated[str, Query()] = "") -> JSONResponse:
    row = await _linked(rt, slug, t)
    stored = await live_version(_store(rt), str(row["workflow_id"]), None, team=str(row["team_id"]))
    return ok(_public(row, _inputs(stored)))


async def _record(rt: Runtime, row: dict[str, Any], outcome: str, sender: str, detail: dict[str, Any]) -> None:
    await TriggerEvents(rt.db).add(
        TriggerEvent(
            team_id=str(row["team_id"]),
            workflow_id=str(row["workflow_id"]),
            source=source_of(str(row["id"])),
            event_key=f"form:{row['id']}:{secrets.token_hex(8)}",
            sender=sender,
            subject=str(row["title"]),
            received_at=datetime.now(UTC).isoformat(),
            outcome=outcome,  # pyright: ignore[reportArgumentType]
            detail=detail,
        )
    )


async def _submit(
    rt: Runtime, row: dict[str, Any], values: dict[str, Any], *, sender: str, created_by: str, via: str | None
) -> dict[str, Any]:
    """Starts the form's run on the live version in the form's team, once its place under the daily cap is taken."""
    stored = await live_version(_store(rt), str(row["workflow_id"]), None, team=str(row["team_id"]))
    _inputs(stored)
    links = _links(rt)
    reserved = await links.reserve(
        str(row["id"]),
        cap=int(row["daily_cap"]),
        since=datetime.now(UTC).date().isoformat(),
        event=TriggerEvent(
            team_id=str(row["team_id"]),
            workflow_id=str(row["workflow_id"]),
            source=source_of(str(row["id"])),
            event_key=f"form:{row['id']}:{secrets.token_hex(8)}",
            sender=sender,
            subject=str(row["title"]),
            received_at=datetime.now(UTC).isoformat(),
            outcome="started",
        ),
    )
    if reserved is None:
        await _record(rt, row, "daily_cap", sender, {"dailyCap": row["daily_cap"]})
        raise TooManyRequests(
            "This form has taken as many requests as it can today. Please try again tomorrow.", code="daily_cap"
        )
    try:
        run, _ = await start_run(
            RunStore(EngineTransactions(rt.db)),
            stored,
            team_id=str(row["team_id"]),
            mode="live",
            input=values,
            run_key=f"form:{row['id']}:{reserved}",
            created_by=created_by,
            started_via=via,
        )
    except Exception as e:
        await links.settle(reserved, run_id=None, failed=f"{type(e).__name__}: {str(e)[:300]}")
        raise
    await links.settle(reserved, run_id=str(run["id"]))
    return {"received": True, "runId": str(run["id"])}


@router.post("/v1/forms/public/{slug}/submit", status_code=202, response_model=Envelope[Received])
async def submit_public(
    rt: Rt, request: Request, slug: str, body: SubmitIn, t: Annotated[str, Query()] = ""
) -> JSONResponse:
    row = await _linked(rt, slug, t)
    address = _address(request, rt.settings.forms_trusted_proxies)
    if limits.hit(f"form:{row['id']}:{address}", PER_MINUTE) is not None:
        await _record(
            rt, row, "rate_limited", address, {"message": "More than 10 submissions in a minute from one address."}
        )
        raise TooManyRequests(
            "Too many submissions from this address. Try again in a minute.", code="form_rate_limited"
        )
    await _submit(rt, row, body.values, sender=address, created_by=FORM_TRIGGER + str(row["id"]), via=None)
    return ok({"received": True}, 202)


@router.post("/v1/forms/public/{slug}/files", status_code=201, response_model=Envelope[UploadedFile])
async def upload_public(
    rt: Rt, request: Request, slug: str, t: Annotated[str, Query()] = "", name: str = "file"
) -> JSONResponse:
    """A file for one of the form's file fields, stored in Files in the form's team and scanned like any upload; the
    answer's `fileId` goes in that field's value."""
    row = await _linked(rt, slug, t)
    files = cast(FilesClient | None, rt.start_files)
    if files is None:
        raise ServiceUnavailable("A form's files are stored in Files, and this service has no Files URL.")
    data = await request.body()
    try:
        stored = await files.write(
            current_tenant(),
            str(row["team_id"]),
            data,
            name=name[:200],
            mime=request.headers.get("content-type") or "application/octet-stream",
            purpose="case_attachment",
            uploaded_by=FORM_TRIGGER + str(row["id"]),
        )
    except FilesRefused as e:
        raise Unprocessable(str(e), code="file_refused") from e
    return ok({"fileId": stored.file.id, "name": stored.file.name}, 201)


async def _member_form(rt: Runtime, me: Principal, slug: str) -> dict[str, Any]:
    """The members-only form at `slug` in one of the person's own teams; anyone else is refused, the same way whether
    the form is another team's or does not exist."""
    for team in dict.fromkeys((me.team_id, *me.team_ids)):
        isolation.enter(current_tenant(), team, kind=FORM)
        row = await _links(rt).by_slug(slug)
        if row is not None and row["mode"] == "members" and not row["paused"]:
            return row
    raise Forbidden("Only members of the team that shares this form can send it.", code="form_members_only")


@router.get("/v1/forms/{slug}/members", response_model=Envelope[PublicForm])
async def member_form(rt: Rt, me: Me, slug: str) -> JSONResponse:
    row = await _member_form(rt, me, slug)
    stored = await live_version(_store(rt), str(row["workflow_id"]), None, team=str(row["team_id"]))
    return ok(_public(row, _inputs(stored)))


@router.post("/v1/forms/{slug}/members", status_code=202, response_model=Envelope[Received])
async def submit_member(rt: Rt, me: Me, slug: str, body: SubmitIn) -> JSONResponse:
    row = await _member_form(rt, me, slug)
    started = await _submit(rt, row, body.values, sender=me.email, created_by=started_by(me), via=HOSTED_FORM)
    return ok(started, 202)
