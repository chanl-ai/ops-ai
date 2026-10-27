"""`/v1/mailboxes`: team mailboxes read for agents-service's Email received trigger and its Test connection (c-192,
c-199), here because a mailbox password is a Secrets-page secret and secret values never leave tools-service.

agents-service owns the mailbox records (Channels > Email) and sends the connection: provider, host, port, login and
the password secret's name (for Microsoft 365, the app registration's tenant and client id, the client secret by its
name, c-228). What bounds that is decided here: only service tokens holding `deployments:run` in a team
are served, the secret is looked up for that team (a secret scoped to another team is refused, each use audited), the
host must be on the tenant's egress allow-list and is dialled at the address `EgressPolicy.dial_address` returns, and
plain IMAP, which sends the password in clear, is refused outside dev and test."""

# No `from __future__ import annotations`: FastAPI reads the route signatures at import.

import imaplib
import socket
import ssl
from dataclasses import asdict
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ops_access import can
from ops_email import GraphSender, ImapMailSource, MailNotConfiguredError, MailSender, ResendSender, SmtpSender
from ops_identity import CurrentService, ServiceCallError, ServiceClient
from ops_service_kit.errors import Forbidden, Unprocessable
from ops_service_kit.http import Envelope, ok
from ops_service_kit.logging import get_logger
from ops_service_kit.settings import Settings

from .egress import EgressDenied, EgressPolicy
from .graph_mailbox import (
    MAIL_SEND,
    CursorRefused,
    CursorSeal,
    GraphClients,
    GraphReader,
    GraphTokens,
    cursor_key,
    hosts,
    roles,
)
from .secrets import SecretMissing, SecretResolver

log = get_logger("ops_tools.mailboxes")
IMAP_DEFAULT_PORT = {True: 993, False: 143}


class _In(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class Connection(_In):
    """How to sign in to one mailbox; the password goes by its secret's name only."""

    address: str = Field(min_length=3, max_length=320)
    provider: Literal["gmail", "imap", "graph"]
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    tls: bool = True
    username: str | None = Field(default=None, max_length=320)
    password_secret: str | None = Field(default=None, max_length=120)
    # Microsoft 365: the app registration's Microsoft tenant and client id; its client secret is `password_secret`.
    graph_tenant_id: str | None = Field(default=None, max_length=64)
    graph_client_id: str | None = Field(default=None, max_length=64)


class ReadIn(_In):
    connection: Connection
    folder: str = "inbox"
    # None: the first pass, which takes the cursor at the folder's end and reads nothing (`now`), or reads from the
    # start when `now` is false.
    cursor: str | None = None
    now: bool = False


class WaitIn(_In):
    connection: Connection
    folder: str = "inbox"
    cursor: str
    seconds: float = Field(default=25.0, gt=0, le=600)


class TestIn(_In):
    connection: Connection
    folder: str = "inbox"


class _Out(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PageOut(_Out):
    items: list[dict[str, Any]]
    next_link: str | None
    delta_link: str | None


class WaitOut(_Out):
    changed: bool


class TestStep(_Out):
    title: str
    state: Literal["done", "failed", "skipped"]


class TestOut(_Out):
    ok: bool
    steps: list[TestStep]
    newest: dict[str, str] | None = None
    error: str | None = None


class _PinnedSSL(imaplib.IMAP4_SSL):
    """IMAP over TLS to an address already checked, verifying the certificate against the host name."""

    def __init__(self, host: str, address: str, port: int, timeout: float) -> None:
        self._address = address
        super().__init__(host, port, ssl_context=ssl.create_default_context(), timeout=timeout)

    def _create_socket(self, timeout: float | None) -> socket.socket:  # pyright: ignore[reportIncompatibleMethodOverride]
        sock = socket.create_connection((self._address, self.port), timeout)
        return self.ssl_context.wrap_socket(sock, server_hostname=self.host)  # pyright: ignore[reportAttributeAccessIssue]


class _PinnedPlain(imaplib.IMAP4):
    def __init__(self, address: str, port: int, timeout: float) -> None:
        self._address = address
        super().__init__(address, port, timeout=timeout)


class MailboxSendRefused(MailNotConfiguredError):
    """A reply cannot leave from the mailbox it names: not the calling team's, no sender, or its secret refused."""


class MailboxSenders:
    """The sender a reply goes out through when `send_reply` names a mailbox (c-200). The mailbox is read from
    agents-service, which owns mailbox records, with a token naming the calling run's tenant and team, so only that
    team's mailbox is found. Its password or API key is a Secrets-page secret looked up for the mailbox's team at each
    send; an SMTP host is dialled at the address the egress allow-list gives, and Resend goes through `resend_http`,
    the egress-checked client."""

    def __init__(
        self,
        settings: Settings,
        agents: ServiceClient,
        *,
        resolver: SecretResolver,
        egress: EgressPolicy,
        resend_http: httpx.AsyncClient,
        graph: GraphClients | None = None,
    ) -> None:
        self.settings = settings
        self.agents = agents
        self.resolver = resolver
        self.egress = egress
        self.resend_http = resend_http
        self.graph = graph
        self.tokens = GraphTokens(settings.graph_login_url, settings.graph_url)

    async def _mailbox(self, tenant: str, team: str, address: str) -> dict[str, Any]:
        try:
            found: list[dict[str, Any]] = await self.agents.get(
                "/v1/channels/mailboxes", params={"address": address}, tenant=tenant, team=team
            )
        except ServiceCallError as e:
            raise MailboxSendRefused(f"agents-service refused the mailbox read: {e.status} {e}") from e
        if not found:
            raise MailboxSendRefused(f"{address} is not a mailbox of {team}.")
        return found[0]

    async def sender(self, tenant: str, team: str, address: str) -> MailSender:
        m = await self._mailbox(tenant, team, address)
        if m.get("sender") == "graph":
            return await self._graph_sender(tenant, team, m)
        kind, secret, sender_from = m.get("sender"), m.get("senderSecret"), m.get("fromAddress")
        if kind not in ("smtp", "resend") or not secret or not sender_from:
            raise MailboxSendRefused(f"{address} has no reply sender; set one on its Channels page.")
        mailbox_team = str(m["teamId"])
        if mailbox_team != team:
            # agents-service answers a team's token with that team's mailboxes only; this holds if it ever did not.
            raise MailboxSendRefused(f"{address} is not a mailbox of {team}.")

        async def password() -> str:
            try:
                values = await self.resolver.lookup(
                    tenant, mailbox_team, [secret], tool="send_reply", actor=f"mailbox:{address}"
                )
            except SecretMissing as e:
                raise MailboxSendRefused(f"The sender's secret {secret} cannot be used: {e}") from e
            return values[secret]

        if kind == "resend":
            return ResendSender(self.resend_http, await password(), sender_from)
        host = m.get("smtpHost") or (self.settings.gmail_smtp_host if m.get("provider") == "gmail" else None)
        if not host:
            raise MailboxSendRefused(f"{address} names no SMTP server.")
        port = int(m.get("smtpPort") or 587)

        async def address_to_dial() -> str:
            try:
                return await self.egress.dial_address(tenant, host, port)
            except EgressDenied as e:
                raise MailboxSendRefused(str(e)) from e

        return SmtpSender(
            host,
            self.egress.dial_port(host, port),
            sender_from,
            username=m.get("username") or m["address"],
            starttls=bool(m.get("smtpStarttls", True)),
            password_source=password,
            address_source=address_to_dial,
        )

    async def _graph_sender(self, tenant: str, team: str, m: dict[str, Any]) -> MailSender:
        """A Microsoft 365 mailbox replies as itself through Graph, with the team's own app registration (c-228)."""
        address, secret = str(m["address"]), m.get("passwordSecret")
        if str(m["teamId"]) != team:
            raise MailboxSendRefused(f"{address} is not a mailbox of {team}.")
        ms_tenant, client_id = m.get("graphTenantId"), m.get("graphClientId")
        if self.graph is None or not (ms_tenant and client_id and secret):
            raise MailboxSendRefused(f"{address} names no Microsoft tenant, client id or client secret.")
        try:
            for host in hosts(self.settings.graph_login_url, self.settings.graph_url):
                await self.egress.dial_address(tenant, host, 443)
            values = await self.resolver.lookup(tenant, team, [secret], tool="send_reply", actor=f"mailbox:{address}")
        except EgressDenied as e:
            raise MailboxSendRefused(str(e)) from e
        except SecretMissing as e:
            raise MailboxSendRefused(f"The mailbox's secret {secret} cannot be used: {e}") from e
        http = self.graph(tenant)
        return GraphSender(http, self.tokens.token(http, tenant, ms_tenant, client_id, values[secret]), address)


def mailboxes_router(
    settings: Settings,
    resolver: SecretResolver | None,
    egress: EgressPolicy | None,
    graph: GraphClients | None = None,
) -> APIRouter:
    """`graph` gives the egress-checked Graph client for a tenant; without it Microsoft 365 mailboxes are not read."""
    r = APIRouter(prefix="/v1/mailboxes", tags=["mailboxes"])
    gmail_host = settings.gmail_imap_host
    tokens = GraphTokens(settings.graph_login_url, settings.graph_url)
    cursors = cursor_key(settings.secrets_key.get_secret_value())

    async def graph_source(caller: Any, conn: Connection, folder: str) -> GraphReader:
        assert resolver is not None and egress is not None
        if graph is None:
            raise Unprocessable("This tools-service reads no Microsoft 365 mailbox.", code="graph_unavailable")
        if not (conn.graph_tenant_id and conn.graph_client_id and conn.password_secret):
            raise Unprocessable(
                f"{conn.address} names no Microsoft tenant, client id or client secret.", code="mailbox_incomplete"
            )
        tenant, secret = caller.tenant_id, conn.password_secret
        try:
            for host in hosts(settings.graph_login_url, settings.graph_url):
                await egress.dial_address(tenant, host, 443)
            values = await resolver.lookup(
                tenant, str(caller.team_id), [secret], tool=f"mailbox:{conn.address}", actor=caller.sub
            )
        except EgressDenied as e:
            raise Forbidden(str(e), code="egress_denied") from e
        except SecretMissing as e:
            raise Forbidden(f"The mailbox's secret {secret} cannot be used: {e}", code="secret_refused") from e
        http = graph(tenant)
        token = tokens.token(http, tenant, conn.graph_tenant_id, conn.graph_client_id, values[secret])
        return GraphReader(http, token, conn.address, folder, seal=CursorSeal(cursors, tenant, conn.address, folder))

    async def source(caller: Any, conn: Connection, folder: str) -> ImapMailSource | GraphReader:
        if resolver is None or egress is None:
            raise Unprocessable("This tools-service has no secrets or egress policy, so it reads no mailbox.")
        can(caller, "deployments", "run", team=caller.team_id, what=f"the mailbox {conn.address}")
        if conn.provider == "graph":
            return await graph_source(caller, conn, folder)
        team = str(caller.team_id)
        host = gmail_host if conn.provider == "gmail" else conn.host
        if not host or not conn.password_secret:
            raise Unprocessable(f"{conn.address} names no IMAP host or password secret.", code="mailbox_incomplete")
        tls = True if conn.provider == "gmail" else conn.tls
        if not tls and settings.environment not in ("dev", "test"):
            raise Unprocessable(
                f"{conn.address} uses plain IMAP, which sends the password in clear; it is refused here.",
                code="plain_imap_refused",
            )
        port = conn.port or IMAP_DEFAULT_PORT[tls]
        tenant, secret = caller.tenant_id, conn.password_secret
        try:
            address = await egress.dial_address(tenant, host, port)
            values = await resolver.lookup(tenant, team, [secret], tool=f"mailbox:{conn.address}", actor=caller.sub)
        except EgressDenied as e:
            raise Forbidden(str(e), code="egress_denied") from e
        except SecretMissing as e:
            raise Forbidden(f"The mailbox's secret {secret} cannot be used: {e}", code="secret_refused") from e
        password, dial, user = values[secret], egress.dial_port(host, port), conn.username or conn.address
        timeout = 30.0

        def connect() -> imaplib.IMAP4:
            c: imaplib.IMAP4 = _PinnedSSL(host, address, dial, timeout) if tls else _PinnedPlain(address, dial, timeout)
            c.login(user, password)
            return c

        return ImapMailSource(connect, folder)

    def failed(mailbox: str, e: Exception) -> Exception:
        log.warning("mailbox_read_failed", mailbox=mailbox, error=type(e).__name__)
        return Unprocessable(f"Reading {mailbox} failed: {e}", code="mailbox_unreachable")

    @r.post("/read", response_model=Envelope[PageOut])
    async def read(body: Annotated[ReadIn, Body()], caller: CurrentService) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """One page of the folder after `cursor`, or with `now` and no cursor, the cursor at its end and no mail."""
        src = await source(caller, body.connection, body.folder)
        try:
            if body.cursor is None and body.now:
                return ok(
                    PageOut(items=[], next_link=None, delta_link=await src.cursor_now()).model_dump(by_alias=True)
                )
            page = await src.delta(body.cursor)
        except CursorRefused as e:
            raise Unprocessable(str(e), code="cursor_refused") from e
        except (imaplib.IMAP4.error, OSError, httpx.HTTPError) as e:
            raise failed(body.connection.address, e) from e
        return ok(PageOut(**asdict(page)).model_dump(by_alias=True))

    @r.post("/wait", response_model=Envelope[WaitOut])
    async def wait(body: Annotated[WaitIn, Body()], caller: CurrentService) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """True as soon as the folder has mail after `cursor` (IDLE); false after `seconds` with none."""
        src = await source(caller, body.connection, body.folder)
        try:
            changed = await src.wait(body.cursor, body.seconds)
        except (imaplib.IMAP4.error, OSError, httpx.HTTPError) as e:
            raise failed(body.connection.address, e) from e
        return ok({"changed": changed})

    @r.post("/test", response_model=Envelope[TestOut])
    async def test(body: Annotated[TestIn, Body()], caller: CurrentService) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Test connection: the secret and host checks, then sign-in and the folder's newest message, read without
        marking it read. A refused check or failed sign-in is a result (ok false, the reason), not an error."""
        graph_box = body.connection.provider == "graph"
        steps = (
            [
                TestStep(title="Use the client secret and the allowed hosts", state="done"),
                TestStep(title="Get a token for the app", state="done"),
                TestStep(title=f"Read {body.folder} without marking anything read", state="done"),
                TestStep(title="Sending is granted (Mail.Send)", state="done"),
            ]
            if graph_box
            else [
                TestStep(title="Use the password secret and the allowed host", state="done"),
                TestStep(title="Sign in", state="done"),
                TestStep(title=f"Read {body.folder} without marking anything read", state="done"),
            ]
        )
        # Who may test is not a result: a caller without the cell is refused like any read.
        can(caller, "deployments", "run", team=caller.team_id, what=f"the mailbox {body.connection.address}")

        def result(failed_at: int, error: str) -> JSONResponse:
            states = ["done"] * failed_at + ["failed"] + ["skipped"] * (len(steps) - failed_at - 1)
            marked = [st.model_copy(update={"state": state}) for st, state in zip(steps, states, strict=True)]
            return ok(TestOut(ok=False, steps=marked, error=error).model_dump(by_alias=True))

        try:
            src = await source(caller, body.connection, body.folder)
        except (Forbidden, Unprocessable) as e:
            return result(0, e.message)
        if isinstance(src, GraphReader):
            return await graph_test(src, result)
        try:
            newest = await src.probe()
        except (imaplib.IMAP4.error, OSError) as e:
            return result(1, str(e) or type(e).__name__)
        return ok(TestOut(ok=True, steps=steps, newest=newest).model_dump(by_alias=True))

    async def graph_test(src: GraphReader, result: Any) -> JSONResponse:
        """The token, then the newest message, then whether the token carries Mail.Send. Nothing is sent: a test
        message would land in someone's inbox."""
        try:
            header = await src.token.header()
        except httpx.HTTPError as e:
            return result(1, f"Microsoft refused the app's credentials: {e}")
        try:
            newest = await src.probe()
        except httpx.HTTPError as e:
            return result(2, f"The mailbox could not be read: {e}")
        granted = roles(header)
        done = [
            TestStep(title=t, state="done")
            for t in (
                "Use the client secret and the allowed hosts",
                "Get a token for the app",
                f"Read {src.folder} without marking anything read",
            )
        ]
        if granted is None:
            # Not a token whose grants can be read; the send step is left unproven rather than reported done.
            sent = TestStep(title="Sending is granted (Mail.Send)", state="skipped")
            return ok(TestOut(ok=True, steps=[*done, sent], newest=newest).model_dump(by_alias=True))
        if MAIL_SEND not in granted:
            return result(3, "The app is not granted Mail.Send, so workflows cannot reply from this mailbox.")
        sent = TestStep(title="Sending is granted (Mail.Send)", state="done")
        return ok(TestOut(ok=True, steps=[*done, sent], newest=newest).model_dump(by_alias=True))

    return r
