"""IMAP against GreenMail, by failure mode: the first pass starts from the mailbox's history; reading marks mail read;
a poll that dies mid-page moves past mail; a renumbered folder (new UIDVALIDITY) replays as new mail; IDLE never wakes
on new mail; a message's attachment, sender or Message-ID is lost in parsing. Mail arrives over GreenMail's SMTP port
and is read over its IMAP port, as from a real mailbox."""

from __future__ import annotations

import asyncio
import base64
import imaplib
import smtplib
from email.message import EmailMessage

import pytest

from ops_email import ImapMailSource, drain
from ops_email.imap import PAGE

from .conftest import GREENMAIL_IMAP, GREENMAIL_SMTP

PDF = b"%PDF-1.4 levy notice"


def message(n: int, to: str, *, attach: bool = True) -> EmailMessage:
    m = EmailMessage()
    m["From"] = "Registry <registry@court.example>"
    m["To"] = to
    m["Subject"] = f"Notice {n}"
    m["Message-ID"] = f"<notice-{n}-{to.split('@', maxsplit=1)[0]}@Court.Example>"
    m["Date"] = "Fri, 17 Oct 2026 10:00:00 +0000"
    m.set_content(f"Notice number {n}.")
    if attach:
        m.add_attachment(PDF, maintype="application", subtype="pdf", filename=f"notice-{n}.pdf")
    return m


def send(to: str, *ns: int, attach: bool = True) -> None:
    with smtplib.SMTP("127.0.0.1", GREENMAIL_SMTP) as s:
        for n in ns:
            s.send_message(message(n, to, attach=attach))


def connect_as(user: str) -> imaplib.IMAP4:
    conn = imaplib.IMAP4("127.0.0.1", GREENMAIL_IMAP)
    conn.login(user, "app-password")
    return conn


def source(user: str, folder: str = "inbox") -> ImapMailSource:
    return ImapMailSource(lambda: connect_as(user), folder)


def key(n: int, user: str) -> str:
    return f"notice-{n}-{user.split('@', maxsplit=1)[0]}@court.example"


async def collect(src: ImapMailSource, link: str | None) -> tuple[list[str], str]:
    keys: list[str] = []

    async def handle(item: dict[str, object]) -> None:
        keys.append(src.parse(item).key)

    cursor, _ = await drain(src, link, handle)
    return keys, cursor


async def test_the_first_pass_starts_after_the_mail_already_there(greenmail: str) -> None:
    send(greenmail, 0, 1, 2)
    src = source(greenmail)
    cursor = await src.cursor_now()
    assert cursor.endswith(":3")
    send(greenmail, 3)
    keys, after = await collect(src, cursor)
    assert keys == [key(3, greenmail)] and after.endswith(":4")


async def test_reading_leaves_mail_unread_and_pages_through_a_backlog(greenmail: str) -> None:
    send(greenmail, *range(PAGE + 3), attach=False)
    src = source(greenmail)
    validity = (await src.cursor_now()).split(":")[1]
    keys, cursor = await collect(src, f"imap:{validity}:0")
    assert len(keys) == PAGE + 3 and cursor == f"imap:{validity}:{PAGE + 3}"
    conn = connect_as(greenmail)
    conn.select('"INBOX"', readonly=True)
    _, flags = conn.uid("FETCH", "1:*", "(FLAGS)")
    conn.logout()
    assert not [f for f in flags if isinstance(f, bytes) and b"\\Seen" in f], flags


async def test_a_poll_that_dies_mid_page_reads_from_the_saved_cursor_again(greenmail: str) -> None:
    send(greenmail, *range(PAGE + 2), attach=False)
    src = source(greenmail)
    start = f"imap:{(await src.cursor_now()).split(':')[1]}:0"
    seen: list[str] = []

    async def dies_at_second_page(item: dict[str, object]) -> None:
        if len(seen) == PAGE:
            raise ConnectionError("lost")
        seen.append(src.parse(item).key)

    with pytest.raises(ConnectionError):
        await drain(src, start, dies_at_second_page)
    keys, _ = await collect(src, start)  # the caller saved no cursor, so it reads from where it was
    assert len(keys) == PAGE + 2


async def test_a_cursor_from_another_uidvalidity_restarts_at_the_end_instead_of_replaying(greenmail: str) -> None:
    """A server that renumbers a folder gives it a new UIDVALIDITY, so a saved cursor names the old one. GreenMail keeps
    a folder's UIDVALIDITY when it is recreated, so the test saves a cursor under another UIDVALIDITY instead."""
    send(greenmail, 0, 1, 2)
    src = source(greenmail)
    validity = int((await src.cursor_now()).split(":")[1])
    keys, cursor = await collect(src, f"imap:{validity - 1}:0")
    assert keys == [] and cursor == f"imap:{validity}:3"


async def test_a_cursor_another_provider_saved_starts_at_the_end_instead_of_failing(greenmail: str) -> None:
    """A mailbox moved to IMAP from another provider keeps the binding's saved cursor, in that provider's form; it is
    read as a first pass, not an error on every poll."""
    send(greenmail, 0, 1)
    src = source(greenmail)
    validity = int((await src.cursor_now()).split(":")[1])
    keys, cursor = await collect(src, "notice-0001.json")
    assert keys == [] and cursor == f"imap:{validity}:2"


LONG_WAIT = 120.0


async def test_idle_wakes_when_mail_arrives_and_times_out_when_none_does(greenmail: str) -> None:
    send(greenmail, 0)
    src = source(greenmail)
    cursor = await src.cursor_now()
    loop = asyncio.get_running_loop()
    started = loop.time()
    assert await src.wait(cursor, 0.5) is False
    assert loop.time() - started >= 0.45

    async def arrive() -> None:
        await asyncio.sleep(1.0)
        await asyncio.to_thread(send, greenmail, 1)

    # Woken by the mail, not by its own timeout: a wait that only re-checked at the timeout would also answer True,
    # so it must return in well under it. A long timeout keeps a loaded machine from failing a working IDLE.
    started = loop.time()
    woke, _ = await asyncio.gather(src.wait(cursor, LONG_WAIT), arrive())
    assert woke is True and loop.time() - started < LONG_WAIT / 2
    # Mail that arrived before the wait is reported at once, without IDLE.
    started = loop.time()
    assert await src.wait(cursor, LONG_WAIT) is True and loop.time() - started < LONG_WAIT / 2


async def test_a_message_parses_to_its_key_sender_subject_body_and_attachment(greenmail: str) -> None:
    send(greenmail, 7)
    src = source(greenmail)
    validity = (await src.cursor_now()).split(":")[1]
    page = await src.delta(f"imap:{validity}:0")
    msg = src.parse(page.items[0])
    assert (msg.key, msg.sender, msg.subject) == (key(7, greenmail), "registry@court.example", "Notice 7")
    assert msg.body == "Notice number 7." and msg.received_at.startswith("2026-10-17T10:00:00")
    [a] = msg.attachments
    assert (a.name, a.mime, a.data()) == ("notice-7.pdf", "application/pdf", PDF)
    assert base64.b64decode(a.content) == PDF


async def test_a_connection_probe_reads_the_newest_headers_without_marking_them_read(greenmail: str) -> None:
    src = source(greenmail)
    assert await src.probe() is None
    send(greenmail, 1, 2)
    newest = await src.probe()
    assert newest is not None and newest["subject"] == "Notice 2" and newest["from"] == "registry@court.example"
    conn = connect_as(greenmail)
    conn.select('"INBOX"', readonly=True)
    _, flags = conn.uid("FETCH", "1:*", "(FLAGS)")
    conn.logout()
    assert not [f for f in flags if isinstance(f, bytes) and b"\\Seen" in f], flags
