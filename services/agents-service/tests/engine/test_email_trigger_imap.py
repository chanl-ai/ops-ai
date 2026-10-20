"""The Email received trigger on an IMAP mailbox (c-192), by failure mode: the first pass downloads the mailbox to skip
it; IDLE never wakes the listener, so mail waits for the next poll; a failing IDLE stops the mailbox being read. The
mailbox is GreenMail (compose); tools-service is faked at its documented `/v1/mailboxes` API, answering from a real
IMAP read of GreenMail, so the listener's gateway source, the cursor and the start path all run as on the stack."""

from __future__ import annotations

import asyncio
import imaplib
import json
import os
import smtplib
import socket
import uuid
from collections.abc import AsyncIterator
from email.message import EmailMessage
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.api.mailbox_gateway import GatewayMailSource
from ops_agents.store.base import metadata
from ops_agents.store.tenancy import current_tenant
from ops_email import ImapMailSource
from ops_engine.store import metadata as engine_metadata
from ops_identity import ServiceClient, dev_service_signer
from ops_service_kit.settings import Settings
from tests.engine.test_email_trigger import TENANT, Env, FakeFiles, connect

SMTP = int(os.environ.get("OPS_GREENMAIL_SMTP_PORT", "3025"))
IMAP = int(os.environ.get("OPS_GREENMAIL_IMAP_PORT", "3143"))


def listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def deliver(to: str, n: int) -> None:
    m = EmailMessage()
    m["From"] = "registry@court.example"
    m["To"] = to
    m["Subject"] = f"Notice of garnishment {n}"
    m["Message-ID"] = f"<g-{n}-{to.split('@', maxsplit=1)[0]}@court.example>"
    m.set_content("Please hold.")
    m.add_attachment(b"%PDF-1.4 notice", maintype="application", subtype="pdf", filename="notice.pdf")
    with smtplib.SMTP("127.0.0.1", SMTP) as s:
        s.send_message(m)


class FakeTools:
    """tools-service's /v1/mailboxes, answered from GreenMail; `fail_wait` makes /wait answer 502."""

    def __init__(self, user: str) -> None:
        self.user = user
        self.calls: list[dict[str, Any]] = []
        self.fail_wait = False

    def source(self, folder: str) -> ImapMailSource:
        def connect() -> imaplib.IMAP4:
            c = imaplib.IMAP4("127.0.0.1", IMAP)
            c.login(self.user, "app-password")
            return c

        return ImapMailSource(connect, folder)

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        body: dict[str, Any] = json.loads(request.content)
        self.calls.append({"path": request.url.path, **body})
        src = self.source(body["folder"])
        if request.url.path == "/v1/mailboxes/wait":
            if self.fail_wait:
                return httpx.Response(502, json={"success": False, "error": {"code": "mailbox_unreachable"}})
            return httpx.Response(
                200, json={"success": True, "data": {"changed": await src.wait(body["cursor"], body["seconds"])}}
            )
        data: dict[str, Any]
        if body.get("now"):
            data = {"items": [], "nextLink": None, "deltaLink": await src.cursor_now()}
        else:
            page = await src.delta(body["cursor"])
            data = {"items": page.items, "nextLink": page.next_link, "deltaLink": page.delta_link}
        return httpx.Response(200, json={"success": True, "data": data})


@pytest.fixture
async def imap(tmp_path: Path) -> AsyncIterator[tuple[Env, FakeTools, str]]:
    if not (listening(SMTP) and listening(IMAP)):
        pytest.skip("GreenMail is not running (make db-up)")
    # A file database: the IDLE task, the poll loop and the test each take their own connection, as on PostgreSQL.
    db = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'agents.db'}", connect_args={"timeout": 30})
    async with db.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    address = f"intake-{uuid.uuid4().hex[:8]}@bank.example"
    await connect(db, TENANT, address, provider="imap", imap_host="mail.bank.test", password_secret="S")
    settings = Settings(email_idle_seconds=10)
    fake_env = Env(db, tmp_path / "unused", FakeFiles(), settings)
    tools = FakeTools(address)
    http = httpx.AsyncClient(base_url="http://tools", transport=httpx.MockTransport(tools))
    fake_env.listener = lambda owner="worker:a", sources=None, _l=fake_env.listener: _l(  # type: ignore[method-assign]
        owner,
        lambda m, folder: GatewayMailSource(
            ServiceClient(http, dev_service_signer(), "agents", "tools", ["deployments:run"], tenant=current_tenant),
            m,
            folder,
        ),
    )
    yield fake_env, tools, address
    await http.aclose()
    await db.dispose()


async def publish_on(env: Env, address: str, **parameters: Any) -> None:
    await env.publish()
    # The workflow watches the IMAP mailbox: rewrite the trigger's mailbox the way a builder would.
    from ops_agents.store.engine import EngineTransactions  # noqa: PLC0415
    from ops_agents.store.tenancy import tenant_scope  # noqa: PLC0415
    from ops_engine.store import DefinitionStore  # noqa: PLC0415

    store = DefinitionStore(EngineTransactions(env.db))
    with tenant_scope(TENANT):
        row = await store.current("levy_intake")
        assert row is not None
        d = row["definition"]
        d["nodes"][0]["parameters"] |= {"mailbox": address, **parameters}
        version, _ = await store.publish(
            "levy_intake", name="Levy", definition=d, digest="i".ljust(64, "i"), now="n", by="b", team="team_ops"
        )
        await store.go_live("levy_intake", version)


async def test_the_first_pass_takes_the_cursor_without_reading_mail(imap: tuple[Env, FakeTools, str]) -> None:
    env, tools, address = imap
    deliver(address, 0)
    deliver(address, 1)
    await publish_on(env, address)
    [result] = await env.listener().poll_all()
    assert result.first_sync and await env.runs() == []
    assert [c for c in tools.calls if not c.get("now")] == [], tools.calls
    deliver(address, 2)
    [result] = await env.listener().poll_all()
    [run] = await env.runs()
    assert run["input"]["subject"] == "Notice of garnishment 2" and len(run["input"]["attachments"]) == 1


async def test_idle_starts_the_run_within_seconds_without_waiting_for_the_poll(
    imap: tuple[Env, FakeTools, str],
) -> None:
    env, _, address = imap
    await publish_on(env, address)
    stop = asyncio.Event()
    # The poll comes round every 120 seconds; only IDLE can start the run inside the wait below.
    task = asyncio.create_task(env.listener().run_forever(stop, 120))
    try:
        await asyncio.sleep(2)  # the first pass took the cursor and the IDLE task is waiting
        deliver(address, 1)
        for _ in range(40):
            if await env.runs():
                break
            await asyncio.sleep(0.25)
        assert len(await env.runs()) == 1
    finally:
        stop.set()
        await asyncio.wait_for(task, 30)


async def test_a_failing_idle_falls_back_to_the_poll(imap: tuple[Env, FakeTools, str]) -> None:
    env, tools, address = imap
    tools.fail_wait = True
    await publish_on(env, address)
    stop = asyncio.Event()
    task = asyncio.create_task(env.listener().run_forever(stop, 1))
    try:
        await asyncio.sleep(1.5)
        deliver(address, 1)
        for _ in range(40):
            if await env.runs():
                break
            await asyncio.sleep(0.25)
        assert len(await env.runs()) == 1
        assert any(c["path"] == "/v1/mailboxes/wait" for c in tools.calls)
    finally:
        stop.set()
        await asyncio.wait_for(task, 30)


def append_again(to: str) -> None:
    """The mailbox's newest message stored again, byte for byte, under a new UID: what a server's redelivery or a
    renumbered folder looks like to a reader."""
    with imaplib.IMAP4("127.0.0.1", IMAP) as c:
        c.login(to, "app-password")
        c.select("INBOX")
        _, found = c.uid("SEARCH", "ALL")
        newest = found[0].split()[-1]
        _, data = c.uid("FETCH", newest, "(BODY.PEEK[])")
        # A FETCH answer is a list of (envelope, bytes) tuples and closing b")" lines.
        fetched: list[tuple[bytes, bytes]] = [cast(tuple[bytes, bytes], p) for p in data if isinstance(p, tuple)]
        raw = fetched[0][1]
        c.append("INBOX", "", imaplib.Time2Internaldate(1.0), raw)


async def test_a_message_reusing_another_ones_message_id_still_starts_its_run(imap: tuple[Env, FakeTools, str]) -> None:
    # Keyed on the sender's Message-ID, a forged one hid a real notice behind an earlier message (QA tick 21).
    env, _, address = imap
    await publish_on(env, address)
    await env.listener().poll_all()  # first pass: takes the cursor
    deliver(address, 1)
    forged = EmailMessage()
    forged["From"] = "registry@court.example"
    forged["To"] = address
    forged["Subject"] = "Notice of garnishment, real one"
    forged["Message-ID"] = f"<g-1-{address.split('@', maxsplit=1)[0]}@court.example>"  # the earlier message's
    forged.set_content("Please hold this one.")
    with smtplib.SMTP("127.0.0.1", SMTP) as s:
        s.send_message(forged)
    await env.listener().poll_all()
    subjects = sorted(r["input"]["subject"] for r in await env.runs())
    assert subjects == ["Notice of garnishment 1", "Notice of garnishment, real one"], subjects


async def test_the_same_message_delivered_again_runs_once(imap: tuple[Env, FakeTools, str]) -> None:
    env, _, address = imap
    await publish_on(env, address)
    await env.listener().poll_all()
    deliver(address, 1)
    await env.listener().poll_all()
    append_again(address)
    await env.listener().poll_all()
    assert len(await env.runs()) == 1


async def events(env: Env) -> list[dict[str, Any]]:
    """The workflow's trigger events, oldest first."""
    from ops_agents.store.tenancy import tenant_scope  # noqa: PLC0415
    from ops_agents.store.trigger_events import TriggerEvents  # noqa: PLC0415

    with tenant_scope(TENANT):
        rows, _ = await TriggerEvents(env.db).page("levy_intake", team_id="team_ops", page=1, page_size=100)
    return list(reversed(rows))


async def test_a_filtered_message_is_listed_with_the_condition_it_failed(imap: tuple[Env, FakeTools, str]) -> None:
    env, _, address = imap
    await publish_on(env, address, subjectContains="garnishment")
    await env.listener().poll_all()
    off_topic = EmailMessage()
    off_topic["From"] = "news@court.example"
    off_topic["To"] = address
    off_topic["Subject"] = "Court holiday hours"
    off_topic.set_content("Closed Monday.")
    with smtplib.SMTP("127.0.0.1", SMTP) as s:
        s.send_message(off_topic)
    await env.listener().poll_all()
    [event] = await events(env)
    assert (event["outcome"], event["run_id"], event["detail"]) == ("filtered", None, {"failed": "subjectContains"})
    assert event["subject"] == "Court holiday hours" and await env.runs() == []


async def test_a_redelivery_is_listed_as_a_duplicate_of_the_run_it_started(imap: tuple[Env, FakeTools, str]) -> None:
    env, _, address = imap
    await publish_on(env, address)
    await env.listener().poll_all()
    deliver(address, 1)
    await env.listener().poll_all()
    append_again(address)
    await env.listener().poll_all()
    [run] = await env.runs()
    assert [(e["outcome"], e["run_id"]) for e in await events(env)] == [
        ("started", run["id"]),
        ("duplicate", run["id"]),
    ]


async def test_mail_past_the_daily_cap_is_listed_and_starts_no_run(imap: tuple[Env, FakeTools, str]) -> None:
    # A filtered message does not use up the cap: only started runs count.
    env, _, address = imap
    await publish_on(env, address, dailyCap=1, hasAttachment=True)
    await env.listener().poll_all()
    plain = EmailMessage()
    plain["From"] = "registry@court.example"
    plain["To"] = address
    plain["Subject"] = "No attachment"
    plain.set_content("See you.")
    with smtplib.SMTP("127.0.0.1", SMTP) as s:
        s.send_message(plain)
    deliver(address, 1)
    deliver(address, 2)
    await env.listener().poll_all()
    outcomes = [(e["subject"], e["outcome"], e["detail"]) for e in await events(env)]
    assert outcomes == [
        ("No attachment", "filtered", {"failed": "hasAttachment"}),
        ("Notice of garnishment 1", "started", {}),
        ("Notice of garnishment 2", "daily_cap", {"dailyCap": 1}),
    ], outcomes
    assert len(await env.runs()) == 1
