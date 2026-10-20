"""`/v1/channels/mailboxes`: the team mailboxes connected on Channels > Email (c-199), which a workflow's Email
received trigger watches.

A mailbox belongs to the team the request acts in and to its tenant; another team's or tenant's mailbox answers 404.
Viewing is every member's (`deployments.view`); connecting and testing an unsaved form need `deployments.create`, and
editing, pausing and testing a saved one `deployments.edit`, in the mailbox's team. Credentials are never sent here: a
password is the name of a Secrets-page secret, read only by tools-service when it signs in."""

from __future__ import annotations

import dataclasses
from typing import Annotated, Any, Literal, TypeAlias

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field

from ops_access import can
from ops_contracts.chat import WireModel
from ops_email import MailboxNotConfiguredError
from ops_engine.store import DefinitionStore
from ops_service_kit.errors import Conflict, NotFound, Unprocessable
from ops_service_kit.http import Envelope
from ops_service_kit.ids import new_id, now_iso

from ...store.engine import EngineTransactions
from ...store.mailboxes import AddressTakenError, MailboxRow, MailboxStore
from ...store.poll_cursors import PollCursors
from ...store.tenancy import current_team, current_tenant
from ..auth import Principal, caller_in, caller_of, principal
from ..deps import Runtime, runtime
from ..email_trigger import binding_of
from ..envelope import ok
from ..mailbox_gateway import GatewayMailSource, mailbox_client
from ..schemas import Out

Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(principal)]  # noqa: UP040

# Every route takes a person or API key (`Me`); the list also answers tools-service, which reads a mailbox's reply
# sender by address when a send_reply names it (c-200), with `deployments:view`.
router = APIRouter(prefix="/v1/channels/mailboxes")
Reader: TypeAlias = Annotated[Principal, Depends(caller_in("deployments"))]  # noqa: UP040

Provider = Literal["gmail", "imap", "graph"]


class MailboxIn(WireModel):
    name: str = Field(min_length=1, max_length=200)
    address: str = Field(pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=320)
    provider: Provider
    imap_host: str | None = Field(default=None, max_length=255)
    imap_port: int | None = Field(default=None, ge=1, le=65535)
    imap_tls: bool = True
    username: str | None = Field(default=None, max_length=320)
    # The name of a Secrets-page secret that holds the password (or app password); never the password itself.
    password_secret: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    folder: str = Field(default="inbox", min_length=1, max_length=200)
    # Microsoft 365 (c-228): the app registration's Microsoft tenant and client id; its client secret is the
    # Secrets-page secret `password_secret` names.
    graph_tenant_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9.-]+$", max_length=64)
    graph_client_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9-]+$", max_length=64)
    sender: Literal["none", "smtp", "resend", "graph"] = "none"
    from_address: str | None = Field(default=None, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=320)
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_starttls: bool = True
    # The SMTP password or Resend API key's secret name; never the value.
    sender_secret: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)


class MailboxPatch(WireModel):
    """The mailbox's name and connection. Pausing is the channel's, through PATCH /v1/channels/{id} alone, so there is
    one way to pause a mailbox."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=320)
    imap_host: str | None = Field(default=None, max_length=255)
    imap_port: int | None = Field(default=None, ge=1, le=65535)
    imap_tls: bool | None = None
    username: str | None = Field(default=None, max_length=320)
    password_secret: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)
    folder: str | None = Field(default=None, min_length=1, max_length=200)
    # Microsoft 365 (c-228): the app registration's Microsoft tenant and client id; its client secret is the
    # Secrets-page secret `password_secret` names.
    graph_tenant_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9.-]+$", max_length=64)
    graph_client_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9-]+$", max_length=64)
    sender: Literal["none", "smtp", "resend", "graph"] | None = None
    from_address: str | None = Field(default=None, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$", max_length=320)
    smtp_host: str | None = Field(default=None, max_length=255)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_starttls: bool | None = None
    sender_secret: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]*$", max_length=120)


class BoundWorkflow(Out):
    id: str
    name: str
    version: int


class MailboxView(Out):
    id: str
    team_id: str
    name: str
    address: str
    provider: Provider
    imap_host: str | None
    imap_port: int | None
    imap_tls: bool
    username: str | None
    password_secret: str | None
    folder: str
    graph_tenant_id: str | None
    graph_client_id: str | None
    sender: Literal["none", "smtp", "resend", "graph"]
    from_address: str | None
    smtp_host: str | None
    smtp_port: int | None
    smtp_starttls: bool
    sender_secret: str | None
    paused: bool
    created_by: str
    created_at: str
    updated_at: str
    # The live workflows whose Email received trigger watches it, and when the listener last read it for them.
    workflows: list[BoundWorkflow]
    last_read_at: str | None


class TestStepView(Out):
    title: str
    state: Literal["done", "failed", "skipped"]


class TestView(Out):
    ok: bool
    steps: list[TestStepView]
    newest: dict[str, str] | None = None
    error: str | None = None


def _team(me: Principal) -> str:
    """The team the request acts in: the selected team, or for a dev session (which reads across teams) its
    X-Team-Id. A mailbox always belongs to one."""
    team = current_team() or me.team_id
    if not team:
        raise Unprocessable(
            "Choose a team with the X-Team-Id header; a mailbox belongs to one team.", code="team_required"
        )
    return team


def _check_sender(m: MailboxRow) -> None:
    """A sender that could not send is refused when saved, never found out at the first reply; so is a Microsoft 365
    mailbox that could not be read."""
    if m.provider == "graph":
        absent = [
            label
            for label, value in (
                ("the Microsoft tenant id", m.graph_tenant_id),
                ("the app's client id", m.graph_client_id),
                ("the client secret's name", m.password_secret),
            )
            if not value
        ]
        if absent:
            raise Unprocessable(f"A Microsoft 365 mailbox needs {', '.join(absent)}.", code="mailbox_incomplete")
    if m.sender == "graph":
        if m.provider != "graph":
            raise Unprocessable("Replies through Microsoft 365 need a Microsoft 365 mailbox.", code="sender_incomplete")
        return
    if m.sender == "none":
        return
    missing = [
        label
        for label, value in (("a from address", m.from_address), ("the sender's secret", m.sender_secret))
        if not value
    ]
    if m.sender == "smtp" and not m.smtp_host and m.provider != "gmail":
        missing.append("an SMTP server")
    if missing:
        raise Unprocessable(f"Replies by {m.sender} need {', '.join(missing)}.", code="sender_incomplete")


def _store(rt: Runtime) -> MailboxStore:
    return MailboxStore(rt.db)


async def _visible(rt: Runtime, me: Principal, mailbox_id: str) -> MailboxRow:
    m = await _store(rt).get(mailbox_id)
    if m is None or m.team_id != _team(me):
        raise NotFound(f"Mailbox {mailbox_id}")
    return m


async def _views(rt: Runtime, rows: list[MailboxRow]) -> list[dict[str, Any]]:
    """Each mailbox joined with the live workflows that watch it and when it was last read, in one pass."""
    tenant = current_tenant()
    live = [r for r in await DefinitionStore(EngineTransactions(rt.db)).live_everywhere() if r["tenant_id"] == tenant]
    bound: dict[str, list[dict[str, Any]]] = {}
    for r in live:
        b = binding_of(r["definition"])
        if b is not None:
            bound.setdefault(b.mailbox.lower(), []).append(r)
    read = await PollCursors(rt.db).read_at([f"email:{r['workflow_id']}" for rs in bound.values() for r in rs])
    out: list[dict[str, Any]] = []
    for m in rows:
        mine = [r for r in bound.get(m.address.lower(), []) if r["team_id"] == m.team_id]
        times = [read[k] for r in mine if (k := f"email:{r['workflow_id']}") in read]
        view = MailboxView(
            **{k: v for k, v in m.values().items() if k in MailboxView.model_fields},
            workflows=[BoundWorkflow(id=r["workflow_id"], name=r["name"], version=r["version"]) for r in mine],
            last_read_at=max(times) if times else None,
        )
        out.append(view.model_dump(mode="json", by_alias=True))
    return out


@router.get("", response_model=Envelope[list[MailboxView]])
async def list_mailboxes(rt: Rt, me: Reader, search: str = "", address: str | None = None) -> JSONResponse:
    """The acting team's mailboxes, by name, each with the workflows that watch it and when it was last read; with
    `address`, only the one at that address. A service token (tools-service sending a reply for a run) holds
    `deployments:view` and names the run's team, so it reads that team's mailboxes and no other's."""
    team = _team(me)
    can(caller_of(me), "deployments", "view", team=team, what="the team's mailboxes")
    rows = await _store(rt).list(team=team, search=search)
    if address:
        rows = [m for m in rows if m.address.lower() == address.lower()]
    return ok(await _views(rt, rows))


@router.post("", response_model=Envelope[MailboxView], status_code=201)
async def connect_mailbox(rt: Rt, me: Me, body: MailboxIn) -> JSONResponse:
    """Connects a mailbox for the acting team. 409 `address_taken` when the tenant has one at this address."""
    team = _team(me)
    can(caller_of(me), "deployments", "create", team=team, what="a mailbox")
    now = now_iso()
    m = MailboxRow(
        id=new_id("mbx"), team_id=team, created_by=me.email, created_at=now, updated_at=now, **body.model_dump()
    )
    _check_sender(m)
    try:
        await _store(rt).create(m)
    except AddressTakenError as e:
        raise Conflict(f"{body.address} is connected already in this workspace.", code="address_taken") from e
    [view] = await _views(rt, [m])
    return ok(view, status=201)


@router.get("/{mailbox_id}", response_model=Envelope[MailboxView])
async def get_mailbox(rt: Rt, me: Me, mailbox_id: str) -> JSONResponse:
    m = await _visible(rt, me, mailbox_id)
    can(caller_of(me), "deployments", "view", team=m.team_id, what="this mailbox")
    [view] = await _views(rt, [m])
    return ok(view)


@router.patch("/{mailbox_id}", response_model=Envelope[MailboxView])
async def edit_mailbox(rt: Rt, me: Me, mailbox_id: str, body: MailboxPatch) -> JSONResponse:
    """Edits a mailbox's name or connection. Its address cannot change while a live workflow watches it (409
    `mailbox_in_use`): the workflow names it by address and would stop receiving mail without a word."""
    m = await _visible(rt, me, mailbox_id)
    can(caller_of(me), "deployments", "edit", team=m.team_id, what="this mailbox")
    values = body.model_dump(exclude_unset=True)
    if "address" in values and values["address"].lower() != m.address.lower():
        [view] = await _views(rt, [m])
        if view["workflows"]:
            names = ", ".join(w["name"] for w in view["workflows"])
            raise Conflict(f"Live workflows watch {m.address} ({names}); unpublish them first.", code="mailbox_in_use")
    _check_sender(dataclasses.replace(m, **values))
    try:
        await _store(rt).update(mailbox_id, {**values, "updated_at": now_iso()})
    except AddressTakenError as e:
        raise Conflict(f"{values.get('address')} is connected already in this workspace.", code="address_taken") from e
    [view] = await _views(rt, [await _visible(rt, me, mailbox_id)])
    return ok(view)


async def _test(rt: Runtime, m: MailboxRow) -> dict[str, Any]:
    def failed(why: str) -> dict[str, Any]:
        return TestView(ok=False, steps=[TestStepView(title="Sign in", state="failed")], error=why).model_dump(
            by_alias=True
        )

    if rt.tools is None:
        return failed("No tools-service is configured, so no mailbox can be read.")
    try:
        result = await GatewayMailSource(mailbox_client(rt.settings, rt.tools.http), m, m.folder).test()
    except (RuntimeError, MailboxNotConfiguredError) as e:
        return failed(str(e))
    return TestView.model_validate(result).model_dump(by_alias=True)


@router.post("/test", response_model=Envelope[TestView])
async def test_unsaved_mailbox(rt: Rt, me: Me, body: MailboxIn) -> JSONResponse:
    """Test connection for the connect form before anything is saved: sign in with the secret and read the folder's
    newest message without marking it read. A failed sign-in is a result with the reason, not an error."""
    team = _team(me)
    can(caller_of(me), "deployments", "create", team=team, what="a mailbox")
    now = now_iso()
    m = MailboxRow(id="unsaved", team_id=team, created_by=me.email, created_at=now, updated_at=now, **body.model_dump())
    return ok(await _test(rt, m))


@router.post("/{mailbox_id}/test", response_model=Envelope[TestView])
async def test_mailbox(rt: Rt, me: Me, mailbox_id: str) -> JSONResponse:
    m = await _visible(rt, me, mailbox_id)
    can(caller_of(me), "deployments", "edit", team=m.team_id, what="this mailbox")
    return ok(await _test(rt, m))
