# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Mail out: the sender protocol every outbound provider implements, and the SMTP, Resend and dev folder providers
(Graph's is in `graph.py`).

`send` takes the caller's idempotency key. The tool gateway claims a write by that key before it runs, so a retried
call reaches a sender once; Resend also receives the key, and SMTP derives the Message-ID from it, so a mail that is
sent twice anyway reaches the receiver with one id.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import smtplib
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Protocol

import httpx


@dataclass(frozen=True)
class OutboundAttachment:
    name: str
    mime: str
    data: bytes

    def base64(self) -> str:
        return base64.b64encode(self.data).decode()


@dataclass(frozen=True)
class OutboundMessage:
    key: str
    to: tuple[str, ...]
    subject: str
    body: str
    attachments: tuple[OutboundAttachment, ...] = ()


class MailSender(Protocol):
    async def send(self, message: OutboundMessage) -> str:
        """Sends the message and returns the provider's reference for it; raises when the provider refused it."""
        ...


class MailNotConfiguredError(RuntimeError):
    """The settings name no mail provider, or one whose secrets are missing."""


def message_id(key: str, sender: str) -> str:
    domain = sender.rpartition("@")[2] or "localhost"
    return f"<{hashlib.sha256(key.encode()).hexdigest()[:32]}@{domain}>"


def mime_message(message: OutboundMessage, sender: str) -> EmailMessage:
    m = EmailMessage()
    m["From"] = sender
    m["To"] = ", ".join(message.to)
    m["Subject"] = message.subject
    m["Message-ID"] = message_id(message.key, sender)
    m.set_content(message.body)
    for a in message.attachments:
        main, _, sub = a.mime.partition("/")
        m.add_attachment(a.data, maintype=main or "application", subtype=sub or "octet-stream", filename=a.name)
    return m


@dataclass
class SmtpSender:
    host: str
    port: int
    sender: str
    username: str | None = None
    password: str | None = None
    starttls: bool = True
    timeout: float = 30.0
    # Read at each send instead of `password` (a Secrets-page secret in tools-service), so a rotation applies at once.
    password_source: Callable[[], Awaitable[str]] | None = None
    # The address to dial for `host`, decided by the caller (tools-service's egress allow-list) right before each send;
    # TLS still verifies the certificate against `host`.
    address_source: Callable[[], Awaitable[str]] | None = None

    def _send(self, m: EmailMessage, password: str | None, address: str | None) -> None:
        with smtplib.SMTP(timeout=self.timeout) as s:
            s.connect(address or self.host, self.port)
            # starttls verifies the certificate against `_host`, which connect set to the address dialled.
            s._host = self.host  # pyright: ignore[reportAttributeAccessIssue]
            if self.starttls:
                s.starttls(context=ssl.create_default_context())
            if self.username:
                s.login(self.username, password or "")
            s.send_message(m)

    async def send(self, message: OutboundMessage) -> str:
        m = mime_message(message, self.sender)
        password = await self.password_source() if self.password_source else self.password
        address = await self.address_source() if self.address_source else None
        await asyncio.to_thread(self._send, m, password, address)
        return str(m["Message-ID"])


class ResendSender:
    """Resend's `POST /emails`; the key goes as `Idempotency-Key`, so Resend sends a repeat once."""

    def __init__(self, http: httpx.AsyncClient, api_key: str, sender: str) -> None:
        self.http = http
        self.api_key = api_key
        self.sender = sender

    async def send(self, message: OutboundMessage) -> str:
        body: dict[str, Any] = {
            "from": self.sender,
            "to": list(message.to),
            "subject": message.subject,
            "text": message.body,
        }
        if message.attachments:
            body["attachments"] = [{"filename": a.name, "content": a.base64()} for a in message.attachments]
        headers = {"Authorization": f"Bearer {self.api_key}", "Idempotency-Key": message.key[:256]}
        r = await self.http.post("/emails", json=body, headers=headers)
        r.raise_for_status()
        return str(r.json()["id"])


@dataclass
class FolderSender:
    """Dev only: each message is written to `folder/<key hash>.json` instead of being sent, so a person or a use case
    can read what went out. A repeated key overwrites its own file."""

    folder: Path
    sender: str

    async def send(self, message: OutboundMessage) -> str:
        self.folder.mkdir(parents=True, exist_ok=True)
        ref = hashlib.sha256(message.key.encode()).hexdigest()[:24]
        record = {
            "reference": ref,
            "key": message.key,
            "from": self.sender,
            "to": list(message.to),
            "subject": message.subject,
            "body": message.body,
            "attachments": [{"name": a.name, "mime": a.mime, "size": len(a.data)} for a in message.attachments],
        }
        (self.folder / f"{ref}.json").write_text(json.dumps(record, indent=2))
        return ref


@dataclass
class MemorySender:
    """Tests only: keeps each message by key."""

    sent: dict[str, OutboundMessage] = field(default_factory=dict[str, OutboundMessage])

    async def send(self, message: OutboundMessage) -> str:
        self.sent.setdefault(message.key, message)
        return hashlib.sha256(message.key.encode()).hexdigest()[:24]


class UnconfiguredSender:
    """No provider is set: every send fails with that reason, so nothing reports sent for mail that never left."""

    async def send(self, message: OutboundMessage) -> str:
        raise MailNotConfiguredError("No mail provider is configured: set OPS_MAIL_PROVIDER and its secrets.")
