"""Microsoft 365 mailboxes with the team's own app registration (c-228), against a fake Graph that checks the client
credentials, the Microsoft tenant and the mailbox, by failure mode: the client secret leaves tools-service; a wrong
secret, an address outside the app's reach or a missing Mail.Send reads as connected; Test connection sends a message;
a Graph host off the tenant's allow-list is dialled; a reply goes out through another registration than the team's; a
read cursor from the caller sends the token to another host or reads another mailbox."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, unquote

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_email import OutboundMessage
from ops_identity import Auth, dev_service_signer, install_auth, mint_service_token
from ops_policy import AesGcmCipher, context_of
from ops_service_kit.http import install_error_handlers
from ops_service_kit.settings import Settings
from ops_tools.egress import EgressPolicy, OverrideResolver
from ops_tools.graph_mailbox import graph_clients
from ops_tools.mailboxes import MailboxSenders, mailboxes_router
from ops_tools.secrets import SecretResolver
from ops_tools.store.egress import EgressStore
from ops_tools.store.secrets import SecretStore

from .service_clients import fake_service
from .test_mailbox_senders import Agents

TEAM, SECRET, MS_TENANT, CLIENT = "team_ops", "M365_CLIENT_SECRET", "contoso-tenant", "app-1"
MAILBOX, FAKE_IP = "levy@contoso.example", "10.77.0.9"
NOTICE: dict[str, Any] = {
    "id": "AAMk1",
    "internetMessageId": "<g-1@court.example>",
    "subject": "Notice of garnishment",
    "from": {"emailAddress": {"address": "registry@court.example"}},
    "receivedDateTime": "2026-10-18T09:00:00Z",
    "body": {"contentType": "text", "content": "See the notice."},
    "internetMessageHeaders": [],
    "hasAttachments": False,
    "attachments": [],
}


def jwt(roles: list[str]) -> str:
    def part(claims: dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")

    return f"{part({'alg': 'none'})}.{part({'roles': roles})}.sig"


class FakeGraph:
    """Microsoft's token endpoint and Graph for one app registration and one mailbox."""

    def __init__(self, secret: str = "s3cret", roles: tuple[str, ...] = ("Mail.Read", "Mail.Send")) -> None:
        self.secret, self.roles = secret, list(roles)
        self.tokens = 0
        self.sent: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.host == "login.microsoftonline.com":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            good = url.path == f"/{MS_TENANT}/oauth2/v2.0/token" and form.get("client_id") == CLIENT
            if not good or form.get("client_secret") != self.secret:
                return httpx.Response(401, json={"error": "invalid_client"})
            self.tokens += 1
            return httpx.Response(200, json={"access_token": jwt(self.roles), "expires_in": 3600})
        assert url.host == "graph.microsoft.com"
        if request.headers.get("authorization") != f"Bearer {jwt(self.roles)}":
            return httpx.Response(401, json={"error": {"code": "InvalidAuthenticationToken"}})
        path = unquote(url.path)
        if not path.startswith(f"/v1.0/users/{MAILBOX}/"):
            return httpx.Response(404, json={"error": {"code": "ErrorInvalidUser"}})
        if path.endswith("/sendMail"):
            if "Mail.Send" not in self.roles:
                return httpx.Response(403, json={"error": {"code": "ErrorAccessDenied"}})
            self.sent.append(json.loads(request.content))
            return httpx.Response(202)
        if path.endswith("/messages/delta"):
            delta = f"https://graph.microsoft.com/v1.0/users/{MAILBOX}/mailFolders/inbox/messages/delta"
            if url.params.get("$deltatoken") == "latest":
                return httpx.Response(200, json={"value": [], "@odata.deltaLink": f"{delta}?$deltatoken=1"})
            return httpx.Response(200, json={"value": [NOTICE], "@odata.deltaLink": f"{delta}?$deltatoken=2"})
        if path.endswith("/messages"):
            return httpx.Response(200, json={"value": [NOTICE]})
        return httpx.Response(404)


def headers(tenant: str) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(),
        service="agents",
        audience="tools",
        tenant_id=tenant,
        scopes=["deployments:run"],
        team_id=TEAM,
    )
    return {"Authorization": f"Bearer {token}"}


def connection(**over: Any) -> dict[str, Any]:
    return {
        "address": MAILBOX,
        "provider": "graph",
        "graphTenantId": MS_TENANT,
        "graphClientId": CLIENT,
        "passwordSecret": SECRET,
    } | over


def policy(engine: AsyncEngine) -> EgressPolicy:
    hosts = {"login.microsoftonline.com": FAKE_IP, "graph.microsoft.com": FAKE_IP}
    return EgressPolicy(EgressStore(engine), OverrideResolver(hosts))


def app_for(engine: AsyncEngine, graph: FakeGraph) -> FastAPI:
    settings = Settings()
    resolver = SecretResolver(SecretStore(engine), AesGcmCipher(settings.secrets_key.get_secret_value()))
    app = FastAPI()
    install_error_handlers(app)
    install_auth(app, Auth.from_settings(settings, audience="tools"))
    clients = graph_clients(httpx.MockTransport(graph), settings.graph_url)
    app.include_router(mailboxes_router(settings, resolver, policy(engine), clients))
    return app


async def allow_and_store(engine: AsyncEngine, tenant: str, *, hosts: bool = True) -> None:
    now = datetime.now(UTC)
    store = EgressStore(engine)
    if hosts:
        for host in ("login.microsoftonline.com", "graph.microsoft.com"):
            await store.add(tenant, "host", host, actor="test", note="", at=now)
        await store.add(tenant, "range", f"{FAKE_IP}/32", actor="test", note="", at=now)
    cipher = AesGcmCipher(Settings().secrets_key.get_secret_value())
    blob = cipher.encrypt("s3cret", context=context_of(tenant, SECRET))
    await SecretStore(engine).create(tenant, TEAM, SECRET, blob, actor="sam", at=now)


@pytest.fixture
async def stores(engine: AsyncEngine, tenant: str) -> AsyncIterator[tuple[AsyncEngine, str]]:
    await allow_and_store(engine, tenant)
    yield engine, tenant


async def call(engine: AsyncEngine, tenant: str, graph: FakeGraph, path: str, **body: Any) -> httpx.Response:
    transport = httpx.ASGITransport(app=app_for(engine, graph))
    async with httpx.AsyncClient(transport=transport, base_url="http://tools") as c:
        payload = {"connection": body.pop("connection", connection()), **body}
        return await c.post(f"/v1/mailboxes/{path}", json=payload, headers=headers(tenant))


async def test_a_mailbox_is_read_with_the_teams_registration_and_the_secret_never_comes_back(
    stores: tuple[AsyncEngine, str],
) -> None:
    engine, tenant = stores
    graph = FakeGraph()
    first = await call(engine, tenant, graph, "read", now=True)
    assert first.status_code == 200, first.text
    page = await call(engine, tenant, graph, "read", cursor=first.json()["data"]["deltaLink"])
    [item] = page.json()["data"]["items"]
    assert item["internetMessageId"] == NOTICE["internetMessageId"]
    assert "s3cret" not in page.text + first.text
    used = await SecretStore(engine).audit(tenant, TEAM)
    assert [u for u in used if u["name"] == SECRET and u["action"] == "used"], used


async def test_test_connection_names_the_step_that_failed_and_sends_nothing(stores: tuple[AsyncEngine, str]) -> None:
    engine, tenant = stores

    async def failed_at(graph: FakeGraph, **conn: Any) -> int | None:
        r = await call(engine, tenant, graph, "test", connection=connection(**conn))
        assert r.status_code == 200, r.text
        states = [s["state"] for s in r.json()["data"]["steps"]]
        return states.index("failed") if "failed" in states else None

    good = FakeGraph()
    assert await failed_at(good) is None and good.sent == [], "a test sends no message"
    assert await failed_at(FakeGraph(secret="rotated")) == 1, "a wrong secret fails at the token"
    assert await failed_at(FakeGraph(), address="nobody@contoso.example") == 2, "an unknown mailbox fails at the read"
    assert await failed_at(FakeGraph(roles=("Mail.Read",))) == 3, "no Mail.Send fails at the send step"


async def test_a_graph_host_off_the_allow_list_is_not_dialled(engine: AsyncEngine, tenant: str) -> None:
    await allow_and_store(engine, tenant, hosts=False)
    graph = FakeGraph()
    r = await call(engine, tenant, graph, "test")
    steps = r.json()["data"]["steps"]
    assert steps[0]["state"] == "failed" and graph.tokens == 0, r.text


async def test_a_reply_leaves_as_the_mailbox_through_the_teams_registration(stores: tuple[AsyncEngine, str]) -> None:
    engine, tenant = stores
    settings = Settings()
    graph = FakeGraph()
    record = {"teamId": TEAM, "address": MAILBOX, "provider": "graph", "sender": "graph"} | {
        "graphTenantId": MS_TENANT,
        "graphClientId": CLIENT,
        "passwordSecret": SECRET,
    }
    senders = MailboxSenders(
        settings,
        fake_service(Agents(record), "agents", ["deployments:view"]),
        resolver=SecretResolver(SecretStore(engine), AesGcmCipher(settings.secrets_key.get_secret_value())),
        egress=policy(engine),
        resend_http=httpx.AsyncClient(),
        graph=graph_clients(httpx.MockTransport(graph), settings.graph_url),
    )
    sender = await senders.sender(tenant, TEAM, MAILBOX)
    await sender.send(
        OutboundMessage(key="reply-1", to=("registry@court.example",), subject="Re: notice", body="Received.")
    )
    [sent] = graph.sent
    assert sent["message"]["subject"] == "Re: notice" and graph.tokens == 1


async def test_a_cursor_reads_only_the_mailbox_it_came_from_and_only_on_graph(stores: tuple[AsyncEngine, str]) -> None:
    engine, tenant = stores
    graph = FakeGraph()
    first = await call(engine, tenant, graph, "read", now=True)
    sealed = first.json()["data"]["deltaLink"]
    other = await call(
        engine, tenant, graph, "read", cursor=sealed, connection=connection(address="ceo@contoso.example")
    )
    raw = [
        "https://evil.example/v1.0/users/levy@contoso.example/mailFolders/inbox/messages/delta",
        "https://graph.microsoft.com/v1.0/users/ceo@contoso.example/mailFolders/inbox/messages/delta",
    ]
    tokens = graph.tokens
    forged = [await call(engine, tenant, graph, "read", cursor=link) for link in raw]
    codes = [(r.status_code, r.json()["error"]["code"]) for r in (other, *forged)]
    assert codes == [(422, "cursor_refused")] * 3, [r.text for r in (other, *forged)]
    assert graph.tokens == tokens, "a refused cursor asks Microsoft for no token"
