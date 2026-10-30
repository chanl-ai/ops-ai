"""The Email received trigger's listener (c-187), by failure mode: mail already in the mailbox starts runs when the
trigger goes live; a redelivery or a second worker starts a second run; a run starts before its attachment is in Files,
or with the bytes in its input; mail that fails a filter starts a run; a paused workflow starts runs from mail; a new
folder continues from the old folder's cursor. The mailbox is the dev fake (a folder of Graph items) and Files is
faked at its documented API (`POST /v1/files`), so the real FilesClient and the real start path run."""

from __future__ import annotations

import asyncio
import base64
import copy
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.email_trigger import Bound, EmailTriggers, SourceFor, run_again, run_key
from ops_agents.store.base import metadata
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.leases import Leases
from ops_agents.store.mailboxes import MailboxRow, MailboxStore
from ops_agents.store.tenancy import tenant_scope
from ops_agents.store.trigger_events import TriggerEvents, trigger_events
from ops_email import message_key
from ops_email.testing import FileMailSource, fake_folder
from ops_engine.store import DefinitionStore, RunStore
from ops_engine.store import metadata as engine_metadata
from ops_files_client import FilesClient
from ops_identity import ServiceClient, dev_service_signer
from ops_service_kit.settings import Settings

TENANT, TEAM, MAILBOX = "acme", "team_ops", "levy@bank.example"
NOTICE: dict[str, Any] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "mailbox" / "levy_notice.json").read_text()
)
PDF = base64.b64decode(NOTICE["attachments"][0]["contentBytes"])


def mail(n: int, **over: Any) -> dict[str, Any]:
    """The levy notice as a new message `n`."""
    item = copy.deepcopy(NOTICE)
    item["internetMessageId"] = f"<notice-{n}@court.example>"
    item["id"] = f"msg-{n}"
    return item | over


async def connect(db: AsyncEngine, tenant: str, address: str, *, team: str = TEAM, **fields: Any) -> MailboxRow:
    """A mailbox record as Channels > Email saves one."""
    m = MailboxRow(
        id=f"mbx_{address.split('@', maxsplit=1)[0]}",
        team_id=team,
        name=address,
        address=address,
        created_by="b",
        created_at="n",
        updated_at="n",
        **cast(Any, {"provider": "imap"} | fields),
    )
    with tenant_scope(tenant):
        await MailboxStore(db).create(m)
    return m


@dataclass
class FakeFiles:
    """files-service's `POST /v1/files` and nothing else: what was stored, by idempotency key."""

    stored: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    down: bool = False
    # Attachment name -> (status, code): files-service's refusal for that file, as its purpose limit answers.
    refuse: dict[str, tuple[int, str]] = field(default_factory=dict[str, tuple[int, str]])

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            return httpx.Response(503, json={"success": False, "error": {"code": "unavailable", "message": "down"}})
        assert request.method == "POST" and request.url.path == "/v1/files"
        if refused := self.refuse.get(request.url.params["name"]):
            status, code = refused
            return httpx.Response(status, json={"success": False, "error": {"code": code, "message": f"{code} here"}})
        key = request.headers["idempotency-key"]
        row = self.stored.setdefault(
            key,
            {
                "id": f"file_{len(self.stored) + 1}",
                "name": request.url.params["name"],
                "mime": request.headers["content-type"],
                "size": len(request.content),
                "digest": "d",
                "purpose": request.url.params["purpose"],
                "team": TEAM,
                "uploadedBy": request.url.params["uploadedBy"],
                "scan": {"status": "clean"},
                "bytes": request.content,
            },
        )
        file = {k: v for k, v in row.items() if k != "bytes"}
        return httpx.Response(201, json={"success": True, "data": {"file": file, "deduplicated": False}})


@dataclass
class Env:
    db: AsyncEngine
    inbox: Path
    files: FakeFiles
    settings: Settings

    def listener(self, owner: str = "worker:a", sources: SourceFor | None = None) -> EmailTriggers:
        http = httpx.AsyncClient(base_url="http://files", transport=httpx.MockTransport(self.files))
        client = FilesClient(ServiceClient(http, dev_service_signer(), "agents", "files"))
        return EmailTriggers(
            self.db,
            sources or (lambda m, folder: FileMailSource(fake_folder(self.inbox.parent, m.address, folder))),
            client,
            Leases(self.db, owner=owner, ttl=30),
            idle_seconds=self.settings.email_idle_seconds,
        )

    def files_client(self) -> FilesClient:
        http = httpx.AsyncClient(base_url="http://files", transport=httpx.MockTransport(self.files))
        return FilesClient(ServiceClient(http, dev_service_signer(), "agents", "files"))

    async def events(self) -> list[dict[str, Any]]:
        """The workflow's trigger list, newest first."""
        with tenant_scope(TENANT):
            rows, _ = await TriggerEvents(self.db).page("levy_intake", team_id=TEAM, page=1, page_size=50)
        return rows

    async def kept(self, event_id: str) -> str | None:
        """The message a set-aside event keeps for Run again."""
        async with self.db.connect() as c:
            t = trigger_events
            return await c.scalar(sa.select(t.c.item).where(t.c.id == event_id))

    def drop(self, item: dict[str, Any], folder: str = "") -> None:
        where = self.inbox / folder if folder else self.inbox
        where.mkdir(parents=True, exist_ok=True)
        (where / f"{item['id']}-{len(list(where.glob('*.json')))}.json").write_text(json.dumps(item))

    async def runs(self, workflow: str = "levy_intake") -> list[dict[str, Any]]:
        with tenant_scope(TENANT):
            return await RunStore(EngineTransactions(self.db)).list(workflow_id=workflow)

    async def publish(
        self, wid: str = "levy_intake", *, tenant: str = TENANT, team: str | None = TEAM, **params: Any
    ) -> None:
        d: dict[str, Any] = {
            "schemaVersion": 2,
            "id": wid,
            "name": "Levy intake",
            "nodes": [
                {
                    "id": "start",
                    "type": "ops.trigger.email",
                    "typeVersion": 1,
                    "name": "Email received",
                    "parameters": {"mailbox": MAILBOX, "folder": "inbox", **params},
                },
                {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {}},
            ],
            "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
        }
        store = DefinitionStore(EngineTransactions(self.db))
        with tenant_scope(tenant):
            digest = str(abs(hash(json.dumps(d, sort_keys=True)))).ljust(64, "0")
            version, _ = await store.publish(
                wid, name="Levy intake", definition=d, digest=digest, now="n", by="b", team=team
            )
            await store.go_live(wid, version)


@pytest.fixture
async def env(tmp_path: Path) -> AsyncIterator[Env]:
    db = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with db.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    settings = Settings()
    await connect(db, TENANT, MAILBOX)
    yield Env(db, tmp_path / MAILBOX, FakeFiles(), settings)
    await db.dispose()


async def test_mail_already_there_starts_nothing_and_new_mail_with_a_pdf_starts_one_run(env: Env) -> None:
    env.drop(mail(0))  # in the mailbox before the trigger went live
    await env.publish()
    [first] = await env.listener().poll_all()
    assert first.first_sync and not first.started
    assert await env.runs() == []
    env.drop(mail(1))
    [second] = await env.listener().poll_all()
    [run] = await env.runs()
    assert second.started == [run["id"]]
    assert run["run_key"].startswith("email:") and run["run_key"] != run_key("notice-1@court.example")
    assert run["created_by"] == f"trigger:email:{MAILBOX}" and run["team_id"] == TEAM and run["mode"] == "live"
    [attachment] = run["input"]["attachments"]
    # The run carries a Files id; the bytes are in Files, stored as the workflow's team.
    [stored] = [f for f in env.files.stored.values() if f["purpose"] == "case_attachment"]
    assert attachment == {
        "fileId": stored["id"],
        "name": NOTICE["attachments"][0]["name"],
        "mime": "application/pdf",
        "size": len(PDF),
    }
    assert stored["bytes"] == PDF and stored["purpose"] == "case_attachment"
    # The text is a file too (c-259), read like an attachment.
    [body] = [f for f in env.files.stored.values() if f["purpose"] == "email_body"]
    assert run["input"]["bodyFile"] == {
        "fileId": body["id"],
        "name": "email-body.txt",
        "mime": "text/plain",
        "size": len(body["bytes"]),
    }
    assert body["bytes"].decode() == NOTICE["body"]["content"]
    assert run["input"]["from"] == "registry@court.example" and "garnishment" in run["input"]["subject"]
    assert "contentBytes" not in json.dumps(run["input"])


async def test_a_redelivery_starts_no_second_run_and_stores_nothing_again(env: Env) -> None:
    await env.publish()
    await env.listener().poll_all()
    env.drop(mail(1))
    await env.listener().poll_all()
    again = mail(1, internetMessageId="NOTICE-1@COURT.EXAMPLE", id="msg-1-again")
    assert message_key(again) != message_key(mail(1))  # the local part's case differs: another message
    same = mail(1, internetMessageId=" notice-1@Court.Example ", id="msg-1-redelivered")
    env.drop(same)
    [result] = await env.listener().poll_all()
    assert result.started == []
    # The attachment and the text, each stored once.
    assert len(await env.runs()) == 1 and len(env.files.stored) == 2


async def test_two_workers_polling_at_once_start_one_run(env: Env) -> None:
    await env.publish()
    await env.listener().poll_all()
    env.drop(mail(1))
    a, b = await asyncio.gather(env.listener("worker:a").poll_all(), env.listener("worker:b").poll_all())
    assert sorted(len(r.started) for r in (*a, *b)) == [0, 1]
    assert len(await env.runs()) == 1


async def test_no_run_starts_before_its_attachment_is_in_files(env: Env) -> None:
    await env.publish()
    await env.listener().poll_all()
    env.drop(mail(1))
    env.files.down = True
    [] = await env.listener().poll_all()  # the binding's pass failed and was logged
    assert await env.runs() == []
    env.files.down = False
    [result] = await env.listener().poll_all()  # the cursor stayed, so the message is read again
    assert len(result.started) == 1 and len(env.files.stored) == 2


async def test_mail_that_fails_a_filter_starts_nothing(env: Env) -> None:
    await env.publish(fromContains="@court.example", subjectContains="garnishment", hasAttachment=True)
    await env.listener().poll_all()
    env.drop(mail(1, attachments=[], hasAttachments=False))
    env.drop(mail(2, subject="Lunch on Friday"))
    env.drop(mail(3, **{"from": {"emailAddress": {"address": "someone@elsewhere.example"}}}))
    env.drop(mail(4))
    [result] = await env.listener().poll_all()
    assert result.skipped == 3
    [run] = await env.runs()
    assert run["input"]["messageId"] == "notice-4@court.example"


async def test_a_paused_workflow_is_not_polled_and_reads_what_arrived_when_resumed(env: Env) -> None:
    await env.publish()
    await env.listener().poll_all()
    with tenant_scope(TENANT):
        await DefinitionStore(EngineTransactions(env.db)).set_paused("levy_intake", True)
    env.drop(mail(1))
    assert await env.listener().poll_all() == []
    assert await env.runs() == []
    with tenant_scope(TENANT):
        await DefinitionStore(EngineTransactions(env.db)).set_paused("levy_intake", False)
    [result] = await env.listener().poll_all()
    assert len(result.started) == 1


async def test_a_new_folder_starts_from_its_own_first_sync(env: Env) -> None:
    await env.publish()
    await env.listener().poll_all()
    env.drop(mail(1), folder="Levies")  # mail in the new folder before the version that watches it went live
    await env.publish(folder="Levies")
    [result] = await env.listener().poll_all()
    assert result.first_sync and await env.runs() == []
    env.drop(mail(2), folder="Levies")
    [result] = await env.listener().poll_all()
    assert len(result.started) == 1


async def test_a_live_workflow_in_another_tenant_or_with_no_team_never_reads_the_mailbox(env: Env) -> None:
    """Versions taken live before the binding rule held (or written by hand) are checked again before every read:
    another tenant's workflow whose team has the same slug, and a workflow no team owns, get none of the mail."""
    await env.publish("other_tenant_intake", tenant="other_tenant")
    await env.publish("unowned_intake", team=None)
    await env.listener().poll_all()
    env.drop(mail(1))
    assert await env.listener().poll_all() == []
    for wid, tenant in (("other_tenant_intake", "other_tenant"), ("unowned_intake", TENANT)):
        with tenant_scope(tenant):
            assert await RunStore(EngineTransactions(env.db)).list(workflow_id=wid) == []
    assert env.files.stored == {}


async def test_a_paused_mailbox_is_not_read_until_it_resumes(env: Env) -> None:
    await env.publish()
    await env.listener().poll_all()
    with tenant_scope(TENANT):
        await MailboxStore(env.db).update(f"mbx_{MAILBOX.split('@', maxsplit=1)[0]}", {"paused": True})
    env.drop(mail(1))
    assert await env.listener().poll_all() == []
    assert await env.runs() == []
    with tenant_scope(TENANT):
        await MailboxStore(env.db).update(f"mbx_{MAILBOX.split('@', maxsplit=1)[0]}", {"paused": False})
    [result] = await env.listener().poll_all()
    assert len(result.started) == 1


def attachment(name: str, mime: str, body: bytes) -> dict[str, Any]:
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": name,
        "contentType": mime,
        "contentBytes": base64.b64encode(body).decode(),
    }


async def test_an_attachment_files_service_refuses_is_skipped_and_the_mailbox_keeps_reading(env: Env) -> None:
    """Over the size limit or a type not allowed is a refusal a retry would meet again: the run starts with what was
    stored and names what was not, and the next message is read. A files-service that is down is not a refusal."""
    await env.publish()
    await env.listener().poll_all()
    # 422 stands for any refusal this service has no name for: it is skipped too, or the message is read for ever.
    env.files.refuse = {
        "big.pdf": (413, "file_too_large"),
        "run.exe": (415, "unsupported_media_type"),
        "odd.bin": (422, "unprocessable"),
    }
    three = NOTICE["attachments"] + [
        attachment("big.pdf", "application/pdf", b"%PDF big"),
        attachment("run.exe", "application/octet-stream", b"MZ"),
        attachment("odd.bin", "application/octet-stream", b"??"),
    ]
    env.drop(mail(1, attachments=three))
    env.drop(mail(2))
    await env.listener().poll_all()
    runs = sorted(await env.runs(), key=lambda r: str(r["input"]["messageId"]))
    assert [r["input"]["messageId"] for r in runs] == ["notice-1@court.example", "notice-2@court.example"]
    first = runs[0]["input"]
    assert [a["name"] for a in first["attachments"]] == [NOTICE["attachments"][0]["name"]]
    assert [(s["name"], s["reason"]) for s in first["skipped"]] == [
        ("big.pdf", "too_large"),
        ("run.exe", "type_not_allowed"),
        ("odd.bin", "refused"),
    ]
    assert runs[1]["input"]["skipped"] == []


async def test_an_upload_in_flight_from_another_workflow_is_read_again_not_dropped(env: Env) -> None:
    # Two workflows on one mailbox store an attachment under one idempotency key; the second meets 409 until the first
    # lands. Taken as a refusal, the second workflow's run started without its notice.
    await env.publish()
    await env.listener().poll_all()
    env.files.refuse = {NOTICE["attachments"][0]["name"]: (409, "upload_in_progress")}
    env.drop(mail(1))
    await env.listener().poll_all()
    assert await env.runs() == []
    env.files.refuse = {}
    await env.listener().poll_all()
    [run] = await env.runs()
    assert [a["name"] for a in run["input"]["attachments"]] == [NOTICE["attachments"][0]["name"]]


async def test_a_database_error_after_a_poll_does_not_stop_the_listener(env: Env) -> None:
    # run_forever used to call bindings() again for IDLE outside the try, so a postgres restart ended the task and
    # mail_listener stayed stopped until the worker was restarted (c-532).
    await env.publish()
    listener = env.listener()
    calls = {"n": 0}
    real = listener.bindings

    async def flaky() -> list[Bound]:
        calls["n"] += 1
        if calls["n"] == 2:
            raise ConnectionError("the database system is starting up")
        return await real()

    listener.bindings = flaky  # type: ignore[method-assign]
    stop = asyncio.Event()
    task = asyncio.create_task(listener.run_forever(stop, 0.02))
    try:
        for _ in range(200):
            if calls["n"] >= 2:
                break
            await asyncio.sleep(0.02)
        assert calls["n"] >= 2, "the listener never reached the second bindings() call"
        env.drop(mail(1))
        for _ in range(200):
            if await env.runs():
                break
            await asyncio.sleep(0.02)
        assert await env.runs(), f"the listener stopped after the database error; bindings calls={calls['n']}"
        assert calls["n"] >= 3
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=2)


async def test_an_email_with_no_attachment_carries_its_text_as_a_file(env: Env) -> None:
    # A body-only email started a run with nothing for Extract from file to read (c-259).
    await env.publish()
    await env.listener().poll_all()
    env.drop(mail(7, attachments=[], hasAttachments=False))
    await env.listener().poll_all()
    [run] = await env.runs()
    assert run["input"]["attachments"] == [] and run["input"]["bodyFile"]["name"] == "email-body.txt", run["input"]
    [stored] = env.files.stored.values()
    assert (stored["purpose"], stored["bytes"].decode()) == ("email_body", NOTICE["body"]["content"])


async def test_a_message_that_fails_three_polls_is_set_aside_and_run_again_starts_it(env: Env) -> None:
    # Its attachment's upload never leaves "in progress": the message fails every read, and before c-561 the mailbox
    # read nothing after it.
    await env.publish()
    await env.listener().poll_all()
    env.files.refuse = {"scan.tif": (409, "upload_in_progress")}
    env.drop(mail(1, attachments=NOTICE["attachments"] + [attachment("scan.tif", "image/tiff", b"II*")]))
    env.drop(mail(2))
    for _ in range(2):
        await env.listener().poll_all()
        assert await env.runs() == [], "the message after it waits while it is tried again"
    await env.listener().poll_all()
    [run] = await env.runs()
    assert run["input"]["messageId"] == "notice-2@court.example", "the mailbox reads on past it"
    events = await env.events()
    assert [e["outcome"] for e in reversed(events)] == ["start_failed", "start_failed", "set_aside", "started"]
    [aside] = [e for e in events if e["outcome"] == "set_aside"]
    assert "item" not in aside and "upload_in_progress" in aside["detail"]["reason"], aside
    assert aside["detail"]["message"].startswith("This email was set aside after 3 failed reads"), aside["detail"]
    assert await env.kept(aside["id"]), "the message is kept for Run again"
    # A failure Run again meets says so and keeps the message.
    with tenant_scope(TENANT), pytest.raises(Exception, match="upload_in_progress"):
        await run_again(env.db, env.files_client(), aside["id"], by="nadia@bank.example")
    assert await env.kept(aside["id"])
    env.files.refuse = {}
    with tenant_scope(TENANT):
        started = await run_again(env.db, env.files_client(), aside["id"], by="nadia@bank.example")
    assert started.run is not None and started.created
    assert started.run["input"]["messageId"] == "notice-1@court.example"
    assert started.run["run_key"] == aside["event_key"], "under the message's own run key"
    assert await env.kept(aside["id"]) is None, "raw mail is not held once its run started"
    assert len(await env.runs()) == 2


async def test_a_set_aside_message_is_forgotten_after_30_days(env: Env) -> None:
    await env.publish()
    await env.listener().poll_all()
    env.files.refuse = {"scan.tif": (409, "upload_in_progress")}
    env.drop(mail(1, attachments=NOTICE["attachments"] + [attachment("scan.tif", "image/tiff", b"II*")]))
    env.drop(mail(3, attachments=NOTICE["attachments"] + [attachment("scan.tif", "image/tiff", b"II*")], subject="x"))
    for _ in range(6):
        await env.listener().poll_all()
    old, recent = sorted((e for e in await env.events() if e["outcome"] == "set_aside"), key=lambda e: e["recorded_at"])
    async with env.db.begin() as c:
        t = trigger_events
        await c.execute(t.update().where(t.c.id == old["id"]).values(recorded_at="2020-01-01T00:00:00.000Z"))
    await env.listener().poll_all()
    assert await env.kept(old["id"]) is None and await env.kept(recent["id"])


async def test_a_message_whose_text_cannot_be_encoded_is_set_aside_too(env: Env) -> None:
    # Graph hands on a broken emoji as a lone surrogate; the message's key, made from its text, cannot be computed.
    await env.publish()
    await env.listener().poll_all()
    env.drop(mail(1, body={"contentType": "text", "content": "Hold the account \ud83d please"}))
    env.drop(mail(2))
    for _ in range(3):
        await env.listener().poll_all()
    [run] = await env.runs()
    assert run["input"]["messageId"] == "notice-2@court.example"
    assert [e["outcome"] for e in reversed(await env.events())] == [
        "start_failed",
        "start_failed",
        "set_aside",
        "started",
    ]


async def test_a_message_the_fault_names_fails_to_start_and_the_fault_is_refused_outside_dev(env: Env) -> None:
    # The dev and test only fault uc-567 uses to set an email aside on a real stack, where no mail fails by itself.
    from pydantic import SecretStr, ValidationError  # noqa: PLC0415

    prod = {"environment": "production", "auth_mode": "platform", "review_key": SecretStr("k" * 32)}
    with pytest.raises(ValidationError, match="email_fault_fail_subject"):
        Settings(**prod, secrets_key=SecretStr("a" * 64), email_fault_fail_subject="garnishment")  # pyright: ignore[reportArgumentType]
    await env.publish()
    listener = env.listener()
    listener.starts.fail_subject = "garnishment"
    await listener.poll_all()
    env.drop(mail(1))
    for _ in range(3):
        await listener.poll_all()
    assert await env.runs() == []
    assert [e["outcome"] for e in reversed(await env.events())] == ["start_failed", "start_failed", "set_aside"]
