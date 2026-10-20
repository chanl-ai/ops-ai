"""IMAP mailboxes read for the Email received trigger and Test connection (c-192, c-199), by failure mode: the
password leaves tools-service; a caller of one team names another team's secret; a host off the egress allow-list is
dialled; a token without `deployments:run`, or of another tenant, reads a mailbox; plain IMAP is used outside dev; Test
connection reports Connected when a check failed. GreenMail (compose) is the mailbox, reached on this machine's
private address as `mail.bank.test`, the way tools-service reaches any outside host."""

from __future__ import annotations

import base64
import os
import smtplib
import socket
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth, dev_service_signer, install_auth, mint_service_token
from ops_policy import AesGcmCipher, context_of
from ops_service_kit.http import install_error_handlers
from ops_service_kit.settings import Settings
from ops_tools.egress import EgressPolicy, OverrideResolver
from ops_tools.mailboxes import mailboxes_router
from ops_tools.secrets import SecretResolver
from ops_tools.store.egress import EgressStore
from ops_tools.store.secrets import SecretStore

SMTP = int(os.environ.get("OPS_GREENMAIL_SMTP_PORT", "3025"))
IMAP = int(os.environ.get("OPS_GREENMAIL_IMAP_PORT", "3143"))
HOST = "mail.bank.test"
SECRET = "INTAKE_IMAP_PASSWORD"
TEAM = "team_ops"


def private_address() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return str(s.getsockname()[0])
    finally:
        s.close()


def listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def headers(tenant: str, *, team: str | None = TEAM, scopes: list[str] | None = None) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(),
        service="agents",
        audience="tools",
        tenant_id=tenant,
        scopes=["deployments:run"] if scopes is None else scopes,
        team_id=team,
    )
    return {"Authorization": f"Bearer {token}"}


def deliver(to: str, n: int) -> None:
    m = EmailMessage()
    m["From"] = "registry@court.example"
    m["To"] = to
    m["Subject"] = f"Notice {n}"
    m["Message-ID"] = f"<notice-{n}-{to.split('@', maxsplit=1)[0]}@court.example>"
    m.set_content("A notice.")
    with smtplib.SMTP("127.0.0.1", SMTP) as s:
        s.send_message(m)


class Env:
    def __init__(self, client: httpx.AsyncClient, tenant: str, address: str, engine: AsyncEngine) -> None:
        self.client, self.tenant, self.address, self.engine = client, tenant, address, engine
        self.connection: dict[str, Any] = {
            "address": address,
            "provider": "imap",
            "host": HOST,
            "port": 143,
            "tls": False,
            "passwordSecret": SECRET,
        }

    async def post(self, path: str, **body: Any) -> httpx.Response:
        h = body.pop("headers", None) or headers(self.tenant)
        return await self.client.post(f"/v1/mailboxes/{path}", json={"connection": self.connection, **body}, headers=h)

    async def read(self, **body: Any) -> httpx.Response:
        return await self.post("read", **body)


def app_for(engine: AsyncEngine, environment: str = "dev") -> FastAPI:
    settings = Settings()
    resolver = SecretResolver(SecretStore(engine), AesGcmCipher(settings.secrets_key.get_secret_value()))
    policy = EgressPolicy(EgressStore(engine), OverrideResolver({HOST: f"{private_address()}:{IMAP}"}))
    app = FastAPI()
    install_error_handlers(app)
    install_auth(app, Auth.from_settings(settings, audience="tools"))
    app.include_router(mailboxes_router(settings.model_copy(update={"environment": environment}), resolver, policy))
    return app


@pytest.fixture
async def env(engine: AsyncEngine, tenant: str) -> AsyncIterator[Env]:
    if not (listening(SMTP) and listening(IMAP)):
        pytest.skip("GreenMail is not running (make db-up)")
    address = f"intake-{uuid.uuid4().hex[:8]}@bank.example"
    now = datetime.now(UTC)
    store = EgressStore(engine)
    await store.add(tenant, "host", HOST, actor="test", note="", at=now)
    await store.add(tenant, "range", f"{private_address()}/32", actor="test", note="", at=now)
    cipher = AesGcmCipher(Settings().secrets_key.get_secret_value())
    blob = cipher.encrypt("app-password", context=context_of(tenant, SECRET))
    await SecretStore(engine).create(tenant, SECRET, blob, actor="sam", at=now, teams=[TEAM])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for(engine)), base_url="http://tools") as c:
        yield Env(c, tenant, address, engine)


async def test_a_mailbox_is_read_with_its_secret_and_the_password_never_comes_back(env: Env) -> None:
    deliver(env.address, 0)
    first = await env.read(now=True)
    assert first.status_code == 200, first.text
    cursor = first.json()["data"]["deltaLink"]
    assert first.json()["data"]["items"] == []
    deliver(env.address, 1)
    page = await env.read(cursor=cursor)
    assert page.status_code == 200, page.text
    [item] = page.json()["data"]["items"]
    assert b"notice-1-" in base64.b64decode(item["rfc822"])
    assert "app-password" not in page.text and "app-password" not in first.text
    used = await SecretStore(env.engine).audit(env.tenant)
    assert [u for u in used if u["name"] == SECRET and u["action"] == "used"], used


async def test_a_caller_of_another_team_cannot_use_this_teams_secret(env: Env) -> None:
    """The secret is looked up for the token's team, so naming team_ops' secret from team_fraud reads nothing."""
    r = await env.read(now=True, headers=headers(env.tenant, team="team_fraud"))
    assert r.status_code == 403 and r.json()["error"]["code"] == "secret_refused", r.text


async def test_a_host_off_the_allow_list_is_not_dialled(env: Env) -> None:
    env.connection["host"] = "mail.elsewhere.test"
    r = await env.read(now=True)
    assert r.status_code == 403 and r.json()["error"]["code"] == "egress_denied", r.text


async def test_a_secret_scoped_to_another_team_is_refused(env: Env) -> None:
    await SecretStore(env.engine).set_teams(env.tenant, SECRET, ["team_fraud"], actor="sam", at=datetime.now(UTC))
    r = await env.read(now=True)
    assert r.status_code == 403 and r.json()["error"]["code"] == "secret_refused", r.text


async def test_only_a_service_with_deployments_run_in_a_team_reads_a_mailbox(env: Env) -> None:
    for h in (headers(env.tenant, scopes=["tools:view"]), headers(env.tenant, team=None)):
        r = await env.read(now=True, headers=h)
        assert r.status_code == 403, r.text


async def test_another_tenants_token_finds_neither_the_host_nor_the_secret(env: Env) -> None:
    r = await env.read(now=True, headers=headers(f"{env.tenant}_other"))
    assert r.status_code == 403 and r.json()["error"]["code"] in ("egress_denied", "secret_refused"), r.text


async def test_plain_imap_is_refused_outside_dev(engine: AsyncEngine, tenant: str) -> None:
    app = app_for(engine, environment="production")
    conn = {"address": "a@bank.example", "provider": "imap", "host": HOST, "tls": False, "passwordSecret": SECRET}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as c:
        r = await c.post("/v1/mailboxes/read", json={"connection": conn, "now": True}, headers=headers(tenant))
    assert r.status_code == 422 and r.json()["error"]["code"] == "plain_imap_refused", r.text


async def test_test_connection_reports_the_newest_message_or_the_step_that_failed(env: Env) -> None:
    deliver(env.address, 3)
    r = await env.post("test")
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["ok"] is True and d["newest"]["subject"] == "Notice 3" and {s["state"] for s in d["steps"]} == {"done"}
    env.connection["host"] = "mail.elsewhere.test"
    d = (await env.post("test")).json()["data"]
    assert d["ok"] is False and [s["state"] for s in d["steps"]] == ["failed", "skipped", "skipped"]
    assert "allow-list" in d["error"]
