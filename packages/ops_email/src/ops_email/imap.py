# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""IMAP: one folder of one mailbox read by UID, over stdlib imaplib in a worker thread.

The cursor is `imap:<UIDVALIDITY>:<last UID read>`. UIDs only grow within one UIDVALIDITY, so "after the last UID" is
the new mail; a server that changes UIDVALIDITY has renumbered the folder, and the source then restarts at the current
end rather than replaying the folder as new mail. Messages are fetched with `BODY.PEEK[]`, which leaves them unread.

imaplib has no IDLE before Python 3.14, so `wait` sends IDLE itself and selects on the socket for the server's
`EXISTS` line. The connection is opened by the caller's `connect`, so the host, the address dialled and the password
are the caller's decision (tools-service: the egress allow-list and the Secrets page).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import imaplib
import re
import select
import ssl
import time
from collections.abc import Callable
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any, cast

from .inbound import DeltaPage, InboundAttachment, InboundMessage, normalise_message_id, synthetic_key

Connect = Callable[[], imaplib.IMAP4]
PAGE = 20


def _cursor(link: str) -> tuple[int, int] | None:
    """UIDVALIDITY and the last UID read, or None for a cursor not in this source's form: one another provider saved
    before the mailbox moved to IMAP."""
    kind, _, rest = link.partition(":")
    validity, _, last = rest.partition(":")
    if kind != "imap" or not validity.isdigit() or not last.isdigit():
        return None
    return int(validity), int(last)


class ImapSession:
    """One logged-in connection with the folder examined (read-only, so nothing is marked read)."""

    def __init__(self, conn: imaplib.IMAP4, folder: str) -> None:
        self.conn = conn
        self.folder = folder
        typ, data = conn.status(self._quoted(), "(UIDVALIDITY UIDNEXT)")
        if typ != "OK":
            raise imaplib.IMAP4.error(f"STATUS {folder}: {data!r}")
        text = b" ".join(d for d in data if isinstance(d, bytes)).decode()
        self.validity = int(re.search(r"UIDVALIDITY (\d+)", text).group(1))  # pyright: ignore[reportOptionalMemberAccess]
        self.next_uid = int(re.search(r"UIDNEXT (\d+)", text).group(1))  # pyright: ignore[reportOptionalMemberAccess]
        typ, data = conn.select(self._quoted(), readonly=True)
        if typ != "OK":
            raise imaplib.IMAP4.error(f"SELECT {folder}: {data!r}")

    def _quoted(self) -> str:
        return '"' + self.folder.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def uids_after(self, last: int) -> list[int]:
        typ, data = self.conn.uid("SEARCH", f"UID {last + 1}:*")
        if typ != "OK":
            raise imaplib.IMAP4.error(f"UID SEARCH: {data!r}")
        found = [int(u) for u in b" ".join(d for d in data if isinstance(d, bytes)).split()]
        # "n:*" always matches the highest UID, even when it is below n (RFC 3501 6.4.8).
        return sorted(u for u in found if u > last)

    def fetch(self, uid: int) -> bytes:
        typ, data = self.conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
        if typ != "OK":
            raise imaplib.IMAP4.error(f"UID FETCH {uid}: {data!r}")
        for part in data:
            if isinstance(part, tuple):
                return bytes(cast(tuple[bytes, bytes], part)[1])
        raise imaplib.IMAP4.error(f"UID FETCH {uid} returned no message")

    def newest(self) -> dict[str, str] | None:
        """From, subject and date of the folder's newest message, read without marking it read; None when empty."""
        uids = self.uids_after(max(0, self.next_uid - 50))
        if not uids:
            return None
        typ, data = self.conn.uid("FETCH", str(uids[-1]), "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        if typ != "OK":
            raise imaplib.IMAP4.error(f"UID FETCH {uids[-1]}: {data!r}")
        raw = next((bytes(cast(tuple[bytes, bytes], p)[1]) for p in data if isinstance(p, tuple)), b"")
        m = message_from_bytes(raw, policy=policy.default)
        return {
            "from": parseaddr(str(m.get("From", "")))[1],
            "subject": str(m.get("Subject", "")),
            "date": str(m.get("Date", "")),
        }

    def idle(self, seconds: float) -> bool:
        """IDLE for up to `seconds`; True when the server announced new mail."""
        conn: Any = self.conn
        tag: bytes = conn._new_tag()  # imaplib has no IDLE before 3.14
        conn.send(tag + b" IDLE\r\n")
        line: bytes = conn.readline()
        if not line.startswith(b"+"):
            raise imaplib.IMAP4.error(f"IDLE refused: {line!r}")
        sock: Any = conn.sock
        changed = False
        deadline = time.monotonic() + seconds
        try:
            while (left := deadline - time.monotonic()) > 0:
                pending = isinstance(sock, ssl.SSLSocket) and sock.pending() > 0
                if not pending and not select.select([sock], [], [], left)[0]:
                    break
                line = conn.readline()
                if not line:
                    raise imaplib.IMAP4.abort("the server closed the connection during IDLE")
                if line.rstrip().endswith(b"EXISTS"):
                    changed = True
                    break
        finally:
            conn.send(b"DONE\r\n")
            while not (line := conn.readline()).startswith(tag):
                if not line:
                    raise imaplib.IMAP4.abort("the server closed the connection ending IDLE")
        return changed

    def close(self) -> None:
        with contextlib.suppress(imaplib.IMAP4.error, OSError):
            self.conn.logout()


def parse_message(raw: bytes) -> InboundMessage:
    """An RFC 822 message as an `InboundMessage`; attachments carry their bytes base64-encoded, as Graph's do."""
    m: EmailMessage = message_from_bytes(raw, policy=policy.default)
    sender = parseaddr(str(m.get("From", "")))[1]
    subject = str(m.get("Subject", ""))
    try:
        received = parsedate_to_datetime(str(m["Date"])).isoformat() if m.get("Date") else ""
    except (TypeError, ValueError):
        received = ""
    mid = str(m.get("Message-ID", "")).strip()
    key = normalise_message_id(mid) if mid else synthetic_key(sender, received, subject)
    refs: list[str] = []
    if m.get("In-Reply-To"):
        refs.append(normalise_message_id(str(m["In-Reply-To"])))
    for r in reversed(str(m.get("References", "")).split()):
        if (n := normalise_message_id(r)) not in refs:
            refs.append(n)
    body_part = m.get_body(preferencelist=("plain", "html"))
    body = body_part.get_content() if body_part is not None else ""
    attachments = tuple(
        InboundAttachment(
            name=a.get_filename() or f"attachment-{i}",
            mime=a.get_content_type(),
            content=base64.b64encode(cast(bytes, a.get_payload(decode=True)) or b"").decode(),
        )
        for i, a in enumerate(m.iter_attachments())
    )
    return InboundMessage(
        key=key,
        sender=sender,
        subject=subject,
        body=str(body).strip(),
        received_at=received,
        references=tuple(refs),
        attachments=attachments,
    )


def parse_item(item: dict[str, Any]) -> InboundMessage:
    """One item `ImapMailSource.delta` returned."""
    return parse_message(base64.b64decode(str(item["rfc822"])))


class ImapMailSource:
    """The `MailSource` over one IMAP folder. Each call opens its own connection through `connect` and logs out."""

    def __init__(self, connect: Connect, folder: str = "INBOX") -> None:
        self.connect = connect
        self.folder = "INBOX" if folder.lower() == "inbox" else folder

    def _session(self) -> ImapSession:
        return ImapSession(self.connect(), self.folder)

    def _delta(self, link: str | None) -> DeltaPage:
        s = self._session()
        try:
            if link is None:
                validity, last = s.validity, 0
            else:
                at = _cursor(link)
                if at is None or at[0] != s.validity:
                    # Renumbered, or another provider's cursor: earlier positions mean nothing here. Restart at the
                    # current end.
                    return DeltaPage([], None, f"imap:{s.validity}:{s.next_uid - 1}")
                validity, last = at
            uids = s.uids_after(last)
            page = uids[:PAGE]
            items = [{"uid": u, "uidValidity": validity, "rfc822": base64.b64encode(s.fetch(u)).decode()} for u in page]
            if len(uids) > PAGE:
                return DeltaPage(items, f"imap:{validity}:{page[-1]}", None)
            return DeltaPage(items, None, f"imap:{validity}:{page[-1] if page else last}")
        finally:
            s.close()

    def _now(self) -> str:
        s = self._session()
        try:
            return f"imap:{s.validity}:{s.next_uid - 1}"
        finally:
            s.close()

    def _wait(self, link: str, seconds: float) -> bool:
        s = self._session()
        try:
            at = _cursor(link)
            # A foreign or renumbered cursor: the next delta resets it, so there is something to do now.
            if at is None or at[0] != s.validity or s.uids_after(at[1]):
                return True
            return s.idle(seconds)
        finally:
            s.close()

    def _probe(self) -> dict[str, str] | None:
        s = self._session()
        try:
            return s.newest()
        finally:
            s.close()

    async def probe(self) -> dict[str, str] | None:
        """Signs in, opens the folder and reads its newest message's headers without marking it read: a connection
        test. Raises what sign-in or the folder raised."""
        return await asyncio.to_thread(self._probe)

    async def delta(self, link: str | None) -> DeltaPage:
        return await asyncio.to_thread(self._delta, link)

    async def cursor_now(self) -> str:
        return await asyncio.to_thread(self._now)

    async def wait(self, link: str, seconds: float) -> bool:
        """True as soon as the folder has mail after `link`, by IDLE; False after `seconds` with none."""
        return await asyncio.to_thread(self._wait, link, seconds)

    def parse(self, item: dict[str, Any]) -> InboundMessage:
        return parse_item(item)
