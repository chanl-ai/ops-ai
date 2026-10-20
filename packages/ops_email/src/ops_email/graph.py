# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Microsoft Graph: the message delta query over a mail folder (in), `sendMail` (out), and the app token both use.

Graph delta returns pages of changed messages: follow `@odata.nextLink` to the end, then keep `@odata.deltaLink` for
the next poll. A message deleted or moved out of the folder comes back as an item with `@removed`; one moved in comes
back as a new item with the same `internetMessageId`, which a consumer's dedupe turns into a no-op.

Not yet run against a tenant (**unverified**): tests drive these classes through a mock transport.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

import httpx

from .inbound import DeltaPage, InboundAttachment, InboundMessage, normalise_message_id, synthetic_key, text_at
from .outbound import OutboundMessage


class GraphToken:
    """An app-only token by client credentials, kept until a minute before it expires."""

    def __init__(
        self, http: httpx.AsyncClient, *, login_url: str, tenant: str, client_id: str, secret: str, scope: str
    ):
        self.http = http
        self.url = f"{login_url.rstrip('/')}/{tenant}/oauth2/v2.0/token"
        self.form = {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": secret,
            "scope": scope,
        }
        self.token = ""
        self.until = 0.0

    async def header(self) -> dict[str, str]:
        if time.monotonic() >= self.until:
            r = await self.http.post(self.url, data=self.form)
            r.raise_for_status()
            body: dict[str, Any] = r.json()
            self.token = str(body["access_token"])
            self.until = time.monotonic() + float(body.get("expires_in", 3600)) - 60
        return {"Authorization": f"Bearer {self.token}"}


def message_key(item: dict[str, Any]) -> str:
    raw = text_at(item, "internetMessageId")
    if raw:
        return normalise_message_id(raw)
    return synthetic_key(
        text_at(item, "from", "emailAddress", "address"), text_at(item, "receivedDateTime"), text_at(item, "subject")
    )


def references(item: dict[str, Any]) -> list[str]:
    raw_headers: list[Any] = list(item.get("internetMessageHeaders") or [])
    headers = {text_at(h, "name").lower(): text_at(h, "value") for h in raw_headers}
    refs: list[str] = []
    if headers.get("in-reply-to"):
        refs.append(normalise_message_id(headers["in-reply-to"]))
    for raw in reversed(headers.get("references", "").split()):
        ref = normalise_message_id(raw)
        if ref not in refs:
            refs.append(ref)
    return refs


def parse_item(item: dict[str, Any]) -> InboundMessage:
    """One Graph message (or `@removed` marker) as an `InboundMessage`."""
    if "@removed" in item:
        return InboundMessage(key=text_at(item, "id"), sender="", subject="", body="", received_at="", removed=True)
    raw_attachments: list[Any] = list(item.get("attachments") or [])
    return InboundMessage(
        key=message_key(item),
        sender=text_at(item, "from", "emailAddress", "address"),
        subject=text_at(item, "subject"),
        body=text_at(item, "body", "content"),
        received_at=text_at(item, "receivedDateTime"),
        references=tuple(references(item)),
        attachments=tuple(
            InboundAttachment(
                name=text_at(a, "name") or f"attachment-{i}",
                mime=text_at(a, "contentType"),
                content=text_at(a, "contentBytes"),
            )
            for i, a in enumerate(raw_attachments)
        ),
    )


class GraphParse:
    def parse(self, item: dict[str, Any]) -> InboundMessage:
        return parse_item(item)


class GraphMailSource(GraphParse):
    """The delta query over one folder of one mailbox. `folder` is a well-known name (`inbox`) or a folder id."""

    SELECT = "internetMessageId,subject,from,receivedDateTime,body,internetMessageHeaders,hasAttachments"

    def __init__(self, http: httpx.AsyncClient, token: GraphToken, mailbox: str, folder: str = "inbox") -> None:
        self.http = http
        self.token = token
        self.mailbox = mailbox
        self.folder = folder

    def _start(self) -> str:
        return (
            f"/v1.0/users/{quote(self.mailbox)}/mailFolders/{quote(self.folder)}/messages/delta"
            f"?$select={self.SELECT}&$expand=attachments"
        )

    async def cursor_now(self) -> str:
        """`$deltatoken=latest` answers with a deltaLink at the current end and no messages."""
        page = await self.delta(self._start() + "&$deltatoken=latest")
        assert page.delta_link is not None, "Graph answers $deltatoken=latest with a deltaLink"
        return page.delta_link

    def _own(self, link: str) -> str:
        """A next or delta link is a URL the token is sent to, so only an https one on this client's own Graph host."""
        url = httpx.URL(link)
        if url.is_absolute_url and (url.scheme != "https" or url.host != self.http.base_url.host):
            raise ValueError(f"{url.host} is not this client's Graph host; the token goes nowhere else")
        return link

    async def delta(self, link: str | None) -> DeltaPage:
        url = self._own(link) if link else self._start()
        headers = {**await self.token.header(), "Prefer": "odata.maxpagesize=50"}
        r = await self.http.get(url, headers=headers)
        r.raise_for_status()
        body: dict[str, Any] = r.json()
        return DeltaPage(list(body.get("value", [])), body.get("@odata.nextLink"), body.get("@odata.deltaLink"))


class GraphSender:
    """`sendMail` as the sending mailbox. Graph returns 202 with no id, so the reference is the caller's key."""

    def __init__(self, http: httpx.AsyncClient, token: GraphToken, sender: str) -> None:
        self.http = http
        self.token = token
        self.sender = sender

    async def send(self, message: OutboundMessage) -> str:
        mail: dict[str, Any] = {
            "subject": message.subject,
            "body": {"contentType": "Text", "content": message.body},
            "toRecipients": [{"emailAddress": {"address": a}} for a in message.to],
            "attachments": [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": a.name,
                    "contentType": a.mime,
                    "contentBytes": a.base64(),
                }
                for a in message.attachments
            ],
        }
        r = await self.http.post(
            f"/v1.0/users/{quote(self.sender)}/sendMail",
            json={"message": mail, "saveToSentItems": True},
            headers=await self.token.header(),
        )
        r.raise_for_status()
        return message.key
