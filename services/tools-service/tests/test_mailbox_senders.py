"""Replies from a mailbox's own sender (c-200), by failure mode: a reply uses another team's mailbox; a mailbox with
no sender reports sent; an SMTP host off the egress allow-list is dialled; the sender's secret is read for the wrong
team; a Resend reply goes out under someone else's key. agents-service's mailbox read is faked at its documented API
(`GET /v1/channels/mailboxes?address=`); SMTP replies go to Mailpit (compose) as to any outside host."""

from __future__ import annotations

import os
import socket
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.activities.catalog import load_catalog
from ops_email import MemorySender, OutboundMessage
from ops_policy import AesGcmCipher, context_of
from ops_service_kit.settings import Settings
from ops_tools.egress import EgressPolicy, OverrideResolver
from ops_tools.mailboxes import MailboxSenders, MailboxSendRefused
from ops_tools.secrets import SecretResolver
from ops_tools.store.egress import EgressStore
from ops_tools.store.secrets import SecretStore
from ops_tools.tools import LocalToolRunner, ToolCaller

from .conftest import AGENTS_FIXTURES
from .service_clients import claims, fake_service

MAILPIT_SMTP = int(os.environ.get("OPS_MAILPIT_SMTP_PORT", "1025"))
MAILPIT_HTTP = int(os.environ.get("OPS_MAILPIT_HTTP_PORT", "8025"))
HOST, SECRET, TEAM = "smtp.bank.test", "DESK_SMTP_PASSWORD", "team_ops"


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


class Agents:
    """agents-service's mailbox list, as a team's service token reads it: only that team's mailbox is found."""

    def __init__(self, mailbox: dict[str, Any]) -> None:
        self.mailbox = mailbox
        self.asked: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        c = claims(request)
        tenant, team = str(c["tenant_id"]), str(c["team_id"])
        self.asked.append((tenant, team))
        m = self.mailbox
        hit = team == m["teamId"] and request.url.params["address"].lower() == m["address"].lower()
        return httpx.Response(200, json={"success": True, "data": [m] if hit else []})


class Env:
    def __init__(self, senders: MailboxSenders, agents: Agents, tenant: str, engine: AsyncEngine) -> None:
        self.senders, self.agents, self.tenant, self.engine = senders, agents, tenant, engine


def build(engine: AsyncEngine, agents: Agents, resend: httpx.MockTransport | None = None) -> MailboxSenders:
    settings = Settings()
    resolver = SecretResolver(SecretStore(engine), AesGcmCipher(settings.secrets_key.get_secret_value()))
    policy = EgressPolicy(EgressStore(engine), OverrideResolver({HOST: f"{private_address()}:{MAILPIT_SMTP}"}))
    return MailboxSenders(
        settings,
        fake_service(agents, "agents", ["deployments:view"]),
        resolver=resolver,
        egress=policy,
        resend_http=httpx.AsyncClient(base_url="https://resend.test", transport=resend),
    )


@pytest.fixture
async def env(engine: AsyncEngine, tenant: str) -> AsyncIterator[Env]:
    if not listening(MAILPIT_SMTP):
        pytest.skip("Mailpit is not running (make db-up)")
    now = datetime.now(UTC)
    store = EgressStore(engine)
    await store.add(tenant, "host", HOST, actor="test", note="", at=now)
    await store.add(tenant, "range", f"{private_address()}/32", actor="test", note="", at=now)
    cipher = AesGcmCipher(Settings().secrets_key.get_secret_value())
    await SecretStore(engine).create(
        tenant,
        TEAM,
        SECRET,
        cipher.encrypt("smtp-password", context=context_of(tenant, SECRET)),
        actor="t",
        at=now,
    )
    agents = Agents(
        {
            "address": f"desk-{uuid.uuid4().hex[:8]}@bank.example",
            "teamId": TEAM,
            "provider": "imap",
            "sender": "smtp",
            "fromAddress": "desk@bank.example",
            "smtpHost": HOST,
            "smtpPort": 587,
            "smtpStarttls": False,
            "senderSecret": SECRET,
            "username": None,
        }
    )
    yield Env(build(engine, agents), agents, tenant, engine)


def message(subject: str) -> OutboundMessage:
    return OutboundMessage(f"run1:reply:{subject}", ("customer@example.com",), subject, "We have your claim.")


async def test_a_reply_leaves_from_the_mailboxs_own_sender(env: Env) -> None:
    subject = f"Your dispute {uuid.uuid4().hex[:8]}"
    sender = await env.senders.sender(env.tenant, TEAM, env.agents.mailbox["address"].upper())
    await sender.send(message(subject))
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{MAILPIT_HTTP}") as api:
        [found] = (await api.get("/api/v1/search", params={"query": f'subject:"{subject}"'})).json()["messages"]
    assert found["From"]["Address"] == "desk@bank.example"
    assert env.agents.asked == [(env.tenant, TEAM)]


async def test_another_teams_mailbox_or_one_without_a_sender_sends_nothing(env: Env) -> None:
    with pytest.raises(MailboxSendRefused, match="not a mailbox of team_fraud"):
        await env.senders.sender(env.tenant, "team_fraud", env.agents.mailbox["address"])
    env.agents.mailbox["sender"] = "none"
    with pytest.raises(MailboxSendRefused, match="no reply sender"):
        await env.senders.sender(env.tenant, TEAM, env.agents.mailbox["address"])


async def test_a_host_off_the_allow_list_is_not_dialled(env: Env) -> None:
    env.agents.mailbox["smtpHost"] = "smtp.elsewhere.test"
    sender = await env.senders.sender(env.tenant, TEAM, env.agents.mailbox["address"])
    with pytest.raises(MailboxSendRefused, match="allow-list"):
        await sender.send(message("refused"))


async def test_the_secret_is_read_for_the_mailboxs_team(env: Env) -> None:
    store, now = SecretStore(env.engine), datetime.now(UTC)
    blob = AesGcmCipher(Settings().secrets_key.get_secret_value()).encrypt("x", context=context_of(env.tenant, SECRET))
    await store.create(env.tenant, "team_fraud", SECRET, blob, actor="t", at=now)
    assert await store.delete(env.tenant, TEAM, SECRET, actor="t", at=now)
    sender = await env.senders.sender(env.tenant, TEAM, env.agents.mailbox["address"])
    with pytest.raises(MailboxSendRefused, match="cannot be used"):
        await sender.send(message("scoped away"))


async def test_resend_sends_with_the_mailboxs_own_key(env: Env) -> None:
    seen: list[httpx.Request] = []

    def resend(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "re_1"})

    env.agents.mailbox["sender"] = "resend"
    senders = build(env.engine, env.agents, httpx.MockTransport(resend))
    ref = await (await senders.sender(env.tenant, TEAM, env.agents.mailbox["address"])).send(message("resend"))
    [r] = seen
    assert ref == "re_1" and r.headers["authorization"] == "Bearer smtp-password"
    assert b'"from":"desk@bank.example"' in r.content.replace(b" ", b"")


def caller(tenant: str, team: str | None) -> ToolCaller:
    return ToolCaller(tenant_id=tenant, team_id=team, sub="service:agents", kind="service")


async def test_send_reply_naming_a_mailbox_sends_through_it_for_the_callers_team_only(env: Env) -> None:
    """Through the runner: the mailbox is read as the caller's team, and a caller of another team, or of none, gets
    the reason and sends nothing (the process sender is never used for a named mailbox)."""
    fallback = MemorySender()
    runner = LocalToolRunner(load_catalog(AGENTS_FIXTURES), fallback, mailbox_sender=env.senders.sender)
    subject = f"Your levy {uuid.uuid4().hex[:8]}"
    reply = {"to": "ana@example.com", "subject": subject, "body": "Held.", "mailbox": env.agents.mailbox["address"]}
    sent = await runner.run("send_reply", reply, key="run1:reply:1", caller=caller(env.tenant, TEAM))
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{MAILPIT_HTTP}") as api:
        [found] = (await api.get("/api/v1/search", params={"query": f'subject:"{subject}"'})).json()["messages"]
    assert sent.ok and found["From"]["Address"] == "desk@bank.example"
    other = await runner.run("send_reply", reply, key="run1:reply:2", caller=caller(env.tenant, "team_fraud"))
    teamless = await runner.run("send_reply", reply, key="run1:reply:3", caller=caller(env.tenant, None))
    assert not other.ok and "not a mailbox of team_fraud" in str(other.output)
    assert not teamless.ok and "names none" in str(teamless.output)
    assert fallback.sent == {}
