"""A mailbox record as a `MailSource` (c-192, c-199). Gmail and IMAP mailboxes are read through tools-service's
`/v1/mailboxes`: the password is a Secrets-page secret and secret values never leave tools-service, so this process
sends the connection from the record (host, login, the secret's name) and tools-service reads it with the secret
scoped to the token's team and the host on the egress allow-list. Each call carries a service token with
`deployments:run` in the mailbox's team, for the tenant the listener acts in. The dev provider is the dev stack's folder
of Graph items."""

from __future__ import annotations

from typing import Any, TypeGuard

import httpx

from ops_email import (
    CursorRefusedError,
    DeltaPage,
    IdleSource,
    InboundMessage,
    MailboxNotConfiguredError,
    MailSource,
)
from ops_email.graph import parse_item as graph_item
from ops_email.imap import parse_item
from ops_identity import ServiceCallError, ServiceClient
from ops_service_kit.logging import get_logger
from ops_service_kit.settings import Settings

from ..store.mailboxes import MailboxRow
from ..store.tenancy import current_tenant

log = get_logger("ops_agents.mailbox_gateway")


class GatewayMailSource:
    def __init__(self, mail: ServiceClient, mailbox: MailboxRow, folder: str) -> None:
        """`mail` is `mailbox_client`: tools-service's mailbox routes, called in the mailbox's team."""
        self.mail = mail
        self.mailbox = mailbox
        self.folder = folder

    async def _post(self, path: str, body: dict[str, Any], timeout: float = 60) -> dict[str, Any]:
        payload = {"connection": connection(self.mailbox), "folder": self.folder, **body}
        try:
            data = await self.mail.post(f"/v1/mailboxes/{path}", payload, team=self.mailbox.team_id, timeout=timeout)
        except ServiceCallError as e:
            raise RuntimeError(f"tools-service refused {path} on {self.mailbox.address}: {e.status} {e}") from e
        return dict(data)

    async def delta(self, link: str | None) -> DeltaPage:
        try:
            d = await self._post("read", {"cursor": link})
        except RuntimeError as e:
            if isinstance(e.__cause__, ServiceCallError) and e.__cause__.code == "cursor_refused":
                raise CursorRefusedError(str(e)) from e.__cause__
            raise
        return DeltaPage(list(d["items"]), d.get("nextLink"), d.get("deltaLink"))

    async def cursor_now(self) -> str:
        return str((await self._post("read", {"cursor": None, "now": True}))["deltaLink"])

    async def wait(self, link: str, seconds: float) -> bool:
        d = await self._post("wait", {"cursor": link, "seconds": seconds}, timeout=seconds + 60)
        return bool(d["changed"])

    def parse(self, item: dict[str, Any]) -> InboundMessage:
        """tools-service hands on an IMAP message as its raw bytes and a Graph one as Graph's JSON."""
        return graph_item(item) if self.mailbox.provider == "graph" else parse_item(item)

    async def test(self) -> dict[str, Any]:
        """tools-service's connection test: sign-in, then the newest message read without marking it read."""
        return await self._post("test", {})


def is_idle(source: MailSource) -> TypeGuard[IdleSource]:
    """Whether the source can wait for new mail (IDLE)."""
    return callable(getattr(source, "wait", None))


def mailbox_client(settings: Settings, http: httpx.AsyncClient) -> ServiceClient:
    """tools-service's mailbox routes: `deployments:run`, in the mailbox's team (named per call), for the tenant the
    caller acts in."""
    return ServiceClient.for_settings(
        settings, http, service="agents", audience="tools", scopes=["deployments:run"], tenant=current_tenant
    )


def connection(m: MailboxRow) -> dict[str, Any]:
    """What tools-service needs to sign in to the mailbox; the password goes by its secret's name only. The Microsoft
    365 fields go only with a Microsoft 365 mailbox, so a tools-service that predates them still reads every other."""
    sign_in: dict[str, Any] = {
        "address": m.address,
        "provider": m.provider,
        "host": m.imap_host,
        "port": m.imap_port,
        "tls": m.imap_tls,
        "username": m.username,
        "passwordSecret": m.password_secret,
    }
    if m.provider == "graph":
        sign_in |= {"graphTenantId": m.graph_tenant_id, "graphClientId": m.graph_client_id}
    return sign_in


def mailbox_source(settings: Settings, mailbox: MailboxRow, folder: str, mail: ServiceClient) -> MailSource:
    """The reader for one folder of a mailbox record, by its provider."""
    if mailbox.provider in ("gmail", "imap", "graph"):
        return GatewayMailSource(mail, mailbox, folder)
    raise MailboxNotConfiguredError(f"{mailbox.address}: reading {mailbox.provider} mailboxes is not built yet.")
