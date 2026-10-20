"""Mail out, by failure mode: a provider picked in code instead of settings, a send that reports success with no
provider, a missing secret found at the first send instead of at start-up, and each provider not sending what it was
given."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx
import pytest

from ops_email import (
    EmailProviders,
    FolderSender,
    GraphSender,
    GraphToken,
    MailboxNotConfiguredError,
    MailNotConfiguredError,
    OutboundAttachment,
    OutboundMessage,
    ResendSender,
    SmtpSender,
    UnconfiguredSender,
)
from ops_email.outbound import mime_message
from ops_service_kit.settings import Settings

from .conftest import MAILPIT_SMTP

MSG = OutboundMessage(
    "run1:send:0:1",
    ("customer@example.com",),
    "Your dispute",
    "We have your claim.",
    (OutboundAttachment("letter.pdf", "application/pdf", b"%PDF-1.4"),),
)


async def test_smtp_delivers_the_message_with_its_attachment_and_a_message_id_from_the_key(mailpit: str) -> None:
    subject = f"Your dispute {uuid.uuid4().hex[:8]}"
    msg = OutboundMessage(MSG.key + subject, MSG.to, subject, MSG.body, MSG.attachments)
    ref = await SmtpSender("127.0.0.1", MAILPIT_SMTP, "ops@bank.example", starttls=False).send(msg)
    async with httpx.AsyncClient(base_url=mailpit) as api:
        found = (await api.get("/api/v1/search", params={"query": f'subject:"{subject}"'})).json()["messages"]
        [summary] = found
        full = (await api.get(f"/api/v1/message/{summary['ID']}")).json()
    assert full["To"][0]["Address"] == "customer@example.com" and full["Subject"] == subject
    # The same key gives the same Message-ID, so a mail sent twice anyway reaches the receiver as one.
    assert f"<{full['MessageID']}>" == ref == str(mime_message(msg, "ops@bank.example")["Message-ID"])
    assert [a["FileName"] for a in full["Attachments"]] == ["letter.pdf"]


async def test_resend_posts_the_key_as_idempotency_key() -> None:
    seen: list[httpx.Request] = []

    def route(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"id": "re_123"})

    http = httpx.AsyncClient(base_url="https://resend.test", transport=httpx.MockTransport(route))
    assert await ResendSender(http, "key", "ops@bank.example").send(MSG) == "re_123"
    [r] = seen
    body = json.loads(r.content)
    assert r.url.path == "/emails" and r.headers["idempotency-key"] == MSG.key
    assert r.headers["authorization"] == "Bearer key"
    assert body["to"] == ["customer@example.com"] and body["attachments"][0]["filename"] == "letter.pdf"


async def test_graph_send_mail_posts_as_the_sending_mailbox() -> None:
    seen: list[httpx.Request] = []

    def route(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        return httpx.Response(202)

    http = httpx.AsyncClient(base_url="https://graph.test", transport=httpx.MockTransport(route))
    token = GraphToken(http, login_url="https://login.test", tenant="t", client_id="c", secret="s", scope="x")
    assert await GraphSender(http, token, "ops@bank.example").send(MSG) == MSG.key
    send = seen[-1]
    assert send.url.path == "/v1.0/users/ops@bank.example/sendMail"
    assert json.loads(send.content)["message"]["toRecipients"] == [
        {"emailAddress": {"address": "customer@example.com"}}
    ]


async def test_no_provider_fails_the_send_instead_of_reporting_sent() -> None:
    with pytest.raises(MailNotConfiguredError):
        await UnconfiguredSender().send(MSG)
    assert isinstance(EmailProviders(Settings(mail_provider="none")).sender(), UnconfiguredSender)


def test_the_provider_comes_from_settings(tmp_path: Path) -> None:
    s = Settings(mail_provider="fake", mail_from="ops@bank.example", mail_fake_out_dir=tmp_path)
    assert isinstance(EmailProviders(s).sender(), FolderSender)
    s = Settings(mail_provider="smtp", mail_from="ops@bank.example", smtp_host="smtp.bank.example")
    assert isinstance(EmailProviders(s).sender(), SmtpSender)
    s = Settings(mail_provider="resend", mail_from="ops@bank.example", resend_api_key="k")  # pyright: ignore[reportArgumentType]
    assert isinstance(EmailProviders(s).sender(), ResendSender)


@pytest.mark.parametrize(
    "settings",
    [
        {"mail_provider": "smtp", "mail_from": "ops@bank.example"},
        {"mail_provider": "resend", "mail_from": "ops@bank.example"},
        {"mail_provider": "graph", "mail_from": "ops@bank.example"},
        {"mail_provider": "smtp", "smtp_host": "h"},
        {
            "mail_provider": "fake",
            "mail_from": "ops@bank.example",
            "environment": "test",
            "auth_mode": "platform",
            "review_key": "r",
            "secrets_key": "ab" * 32,
        },
    ],
)
def test_a_missing_secret_or_a_fake_outside_dev_refuses_at_start_up(settings: dict[str, str]) -> None:
    with pytest.raises(MailNotConfiguredError):
        EmailProviders(Settings(**settings))  # pyright: ignore[reportArgumentType]


def test_a_graph_mailbox_without_credentials_refuses_and_none_reads_nothing() -> None:
    with pytest.raises(MailboxNotConfiguredError):
        EmailProviders(Settings(mailbox_source="graph"))
    with pytest.raises(MailboxNotConfiguredError):
        EmailProviders(Settings()).source("a@b.example")


async def test_the_dev_fake_writes_what_went_out(tmp_path: Path) -> None:
    ref = await FolderSender(tmp_path, "ops@bank.example").send(MSG)
    record = json.loads((tmp_path / f"{ref}.json").read_text())
    assert record["to"] == ["customer@example.com"] and record["attachments"][0]["size"] == 8
