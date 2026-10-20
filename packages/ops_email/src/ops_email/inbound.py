# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Mail in: the source protocol every inbound provider implements, the message it parses to, and the delta drain.

A source serves pages of changes since a cursor: follow `next_link` to the end, then keep `delta_link` for the next
poll. Items are the provider's own JSON, so a consumer can store one and parse it again later; `parse` turns one into
an `InboundMessage`. A message deleted or moved out of the folder parses with `removed` set.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast


@dataclass(frozen=True)
class DeltaPage:
    items: list[dict[str, Any]]
    next_link: str | None
    delta_link: str | None


@dataclass(frozen=True)
class InboundAttachment:
    name: str
    # "" when the provider did not say.
    mime: str
    # As the provider sent it: base64 for a real mailbox. Fixture mail may carry plain text here.
    content: str

    def data(self) -> bytes:
        """The attachment's bytes; raises `binascii.Error` when `content` is not base64."""
        return base64.b64decode(self.content, validate=True)


@dataclass(frozen=True)
class InboundMessage:
    # The normalised Message-ID, or a synthetic key when the message has none. Replies thread on it; runs are keyed on
    # `fingerprint`, since a sender chooses its Message-ID.
    key: str
    sender: str
    subject: str
    body: str
    received_at: str
    # In-Reply-To first, then References newest to oldest: the order in which to look for the case a reply belongs to.
    references: tuple[str, ...] = ()
    attachments: tuple[InboundAttachment, ...] = ()
    removed: bool = False

    @property
    def fingerprint(self) -> str:
        """The message's identity for starting one run per message: its Message-ID with what it says. Another message
        reusing that Message-ID differs and runs; a redelivery, under a new UID or with new Received headers, does not.
        The received time is left out: a provider stamps its own on each delivery."""
        h = hashlib.sha256()
        for part in (self.key, self.sender.lower(), self.subject.strip(), self.body.strip()):
            h.update(part.encode())
            h.update(b"\0")
        for a in self.attachments:
            h.update(f"{a.name}\0{a.mime}\0{a.content}\0".encode())
        return h.hexdigest()


class MailSource(Protocol):
    async def delta(self, link: str | None) -> DeltaPage:
        """`link` is None for the first sync, else the nextLink or deltaLink the previous page returned."""
        ...

    async def cursor_now(self) -> str:
        """A cursor at the current end of the folder, taken without reading any message: a first pass that should
        start nothing for mail already there begins here."""
        ...

    def parse(self, item: dict[str, Any]) -> InboundMessage: ...


class IdleSource(Protocol):
    async def wait(self, link: str, seconds: float) -> bool:
        """True as soon as the folder has mail after `link`; False after `seconds` with none."""
        ...


class MailboxNotConfiguredError(RuntimeError):
    """The settings name no mail source, or one whose secrets are missing."""


class CursorRefusedError(RuntimeError):
    """The source no longer accepts a stored cursor (its key changed, or the cursor predates sealing). Mail that
    arrived after that cursor cannot be read from it; the caller takes a fresh one and says what was skipped."""


def text_at(d: Any, *path: str) -> str:
    """The string at `path` in a provider's JSON, or "" when a step is missing; Graph omits empty properties."""
    for step in path:
        if not isinstance(d, dict):
            return ""
        d = cast(dict[str, Any], d).get(step)
    return "" if d is None else str(d)


def normalise_message_id(raw: str) -> str:
    """Message-IDs arrive with and without angle brackets and with varying case. The local part is case-sensitive by
    RFC 5322 and kept as is; the domain is not, and is lower-cased."""
    mid = raw.strip().strip("<>").strip()
    local, at, domain = mid.rpartition("@")
    return f"{local}@{domain.lower()}" if at else mid


def synthetic_key(sender: str, received_at: str, subject: str) -> str:
    """The key of a message with no Message-ID: who sent it, when and the subject, so a redelivery still matches."""
    basis = f"{sender.lower()}|{received_at}|{subject.strip()}"
    return "synthetic:" + hashlib.sha256(basis.encode()).hexdigest()[:32]


@dataclass(frozen=True)
class EmailFilter:
    """Which messages a watcher takes. Each set condition must hold; text matches ignore case."""

    from_contains: str = ""
    subject_contains: str = ""
    has_attachment: bool = False

    def matches(self, m: InboundMessage) -> bool:
        return self.failed(m) is None

    def failed(self, m: InboundMessage) -> str | None:
        """The first condition `m` does not meet, by its trigger parameter name; None when it meets them all."""
        if self.from_contains and self.from_contains.lower() not in m.sender.lower():
            return "fromContains"
        if self.subject_contains and self.subject_contains.lower() not in m.subject.lower():
            return "subjectContains"
        if self.has_attachment and not m.attachments:
            return "hasAttachment"
        return None


async def drain(
    source: MailSource, link: str | None, handle: Callable[[dict[str, Any]], Awaitable[None]]
) -> tuple[str, int]:
    """Hands every item from `link` to the end of the delta to `handle`, in order, and returns the cursor for the next
    poll with the number of pages read. The caller saves the cursor only after this returns: a poll that dies part-way
    starts again from the previous cursor, so `handle` must make a repeated item a no-op."""
    pages = 0
    while True:
        page = await source.delta(link)
        pages += 1
        for item in page.items:
            await handle(item)
        if page.next_link is not None:
            link = page.next_link
            continue
        if page.delta_link is None:
            raise ValueError("the mail source ended a sync with neither a next link nor a delta link")
        return page.delta_link, pages
