"""Microsoft 365 mailboxes through Graph with the team's own app registration (c-228): the Microsoft tenant id and
client id on the mailbox record, the client secret a Secrets-page secret. Every Graph and token request goes through
the egress transport marked with the calling tenant, so it is dialled only when the tenant's allow-list holds the host.
A token is kept per registration and secret value until a minute before it expires (ops_email.GraphToken)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import quote, urlsplit

import httpx

from ops_email import DeltaPage, GraphMailSource, GraphToken

from .egress import TENANT_EXTENSION, no_cookie_jar

# Graph has no IDLE here: a wait sleeps this long at most and reports possible mail, and the listener's read decides.
GRAPH_WAIT_S = 15.0
MAIL_SEND = "Mail.Send"

GraphClients = Callable[[str], httpx.AsyncClient]


def graph_clients(transport: httpx.AsyncBaseTransport, base_url: str) -> GraphClients:
    """One client per tenant over `transport`, each request marked with that tenant so the egress transport dials it
    through that tenant's allow-list. No redirects, proxies or cookies, as for every outbound call."""
    made: dict[str, httpx.AsyncClient] = {}

    def client(tenant: str) -> httpx.AsyncClient:
        if tenant not in made:

            async def mark(request: httpx.Request) -> None:
                request.extensions[TENANT_EXTENSION] = tenant

            made[tenant] = httpx.AsyncClient(
                transport=transport,
                base_url=base_url,
                event_hooks={"request": [mark]},
                trust_env=False,
                follow_redirects=False,
                cookies=no_cookie_jar(),
                timeout=30,
            )
        return made[tenant]

    return client


class GraphTokens:
    """App-only tokens by registration, so a wait loop does not ask for one on every call; a rotated secret gets a
    new one."""

    def __init__(self, login_url: str, graph_url: str) -> None:
        self.login_url, self.scope = login_url, f"{graph_url.rstrip('/')}/.default"
        self.kept: dict[tuple[str, str, str, str], GraphToken] = {}

    def token(self, http: httpx.AsyncClient, tenant: str, ms_tenant: str, client_id: str, secret: str) -> GraphToken:
        key = (tenant, ms_tenant, client_id, hashlib.sha256(secret.encode()).hexdigest())
        if key not in self.kept:
            self.kept[key] = GraphToken(
                http, login_url=self.login_url, tenant=ms_tenant, client_id=client_id, secret=secret, scope=self.scope
            )
        return self.kept[key]


def hosts(login_url: str, graph_url: str) -> list[str]:
    """The two hosts a Graph mailbox dials, for the allow-list check before any call."""
    return [str(urlsplit(u).hostname) for u in (login_url, graph_url)]


def roles(header: dict[str, str]) -> list[str] | None:
    """The application permissions an app-only token carries (its `roles` claim), read without verifying it: the
    caller only wants to say which grant is missing. None when the token is not a readable JWT."""
    token = header.get("Authorization", "").removeprefix("Bearer ")
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except (ValueError, json.JSONDecodeError):
        return None
    found = cast(dict[str, Any], payload).get("roles") if isinstance(payload, dict) else None
    return [str(r) for r in cast(list[Any], found)] if isinstance(found, list) else []


class CursorRefused(ValueError):
    pass


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def cursor_key(secrets_key: str) -> bytes:
    """The key read cursors are sealed with, derived from the secrets key so it needs no setting of its own."""
    return hashlib.sha256(b"graph-cursor:" + secrets_key.encode()).digest()


@dataclass(frozen=True)
class CursorSeal:
    """Graph's next and delta links are URLs that the bearer token is sent to. They leave this service sealed with its
    key, the tenant, the mailbox and the folder they read, and a cursor comes back only if it opens for the same ones.
    A caller therefore cannot choose the host that receives the token or the mailbox that is read."""

    key: bytes
    tenant: str
    mailbox: str
    folder: str

    def _claims(self) -> list[str]:
        return [self.tenant, self.mailbox.lower(), self.folder]

    def close(self, link: str | None) -> str | None:
        if link is None:
            return None
        payload = json.dumps([*self._claims(), link]).encode()
        return f"{_b64(payload)}.{_b64(hmac.new(self.key, payload, hashlib.sha256).digest())}"

    def open(self, cursor: str) -> str:
        payload_text, _, mac = cursor.partition(".")
        try:
            payload = _unb64(payload_text)
            good = hmac.compare_digest(_unb64(mac), hmac.new(self.key, payload, hashlib.sha256).digest())
            claims = cast(list[str], json.loads(payload)) if good else []
        except (ValueError, TypeError):
            claims = []
        if claims[:3] != self._claims() or len(claims) != 4:
            raise CursorRefused(f"This cursor was not issued for {self.mailbox}; start again without one.")
        return claims[3]


class GraphReader(GraphMailSource):
    """The delta reader plus what the trigger and Test connection call besides it. Its cursors are sealed
    (`CursorSeal`): the caller keeps them but cannot write one."""

    def __init__(
        self, http: httpx.AsyncClient, token: GraphToken, mailbox: str, folder: str, *, seal: CursorSeal
    ) -> None:
        super().__init__(http, token, mailbox, folder)
        self.seal = seal

    async def cursor_now(self) -> str:
        page = await GraphMailSource.delta(self, self._start() + "&$deltatoken=latest")
        sealed = self.seal.close(page.delta_link)
        assert sealed is not None, "Graph answers $deltatoken=latest with a deltaLink"
        return sealed

    async def delta(self, link: str | None) -> DeltaPage:
        page = await GraphMailSource.delta(self, self.seal.open(link) if link else None)
        return DeltaPage(page.items, self.seal.close(page.next_link), self.seal.close(page.delta_link))

    async def wait(self, link: str, seconds: float) -> bool:
        """Graph has no IDLE here: wait a short while, then say there may be mail; the read decides."""
        await asyncio.sleep(min(seconds, GRAPH_WAIT_S))
        return True

    async def probe(self) -> dict[str, str] | None:
        """From, subject and date of the folder's newest message, read without marking it read; None when empty."""
        path = f"/v1.0/users/{quote(self.mailbox)}/mailFolders/{quote(self.folder)}/messages"
        params = {"$top": "1", "$select": "from,subject,receivedDateTime", "$orderby": "receivedDateTime desc"}
        r = await self.http.get(path, params=params, headers=await self.token.header())
        r.raise_for_status()
        body = cast(dict[str, Any], r.json())
        items = cast(list[dict[str, Any]], body.get("value") or [])
        if not items:
            return None
        newest = items[0]
        origin = cast(dict[str, Any], newest.get("from") or {})
        sender = cast(dict[str, Any], origin.get("emailAddress") or {})
        return {
            "from": str(sender.get("address") or ""),
            "subject": str(newest.get("subject") or ""),
            "date": str(newest.get("receivedDateTime") or ""),
        }
