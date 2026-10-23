"""A test email runs as a mailbox email does (c-466), on PostgreSQL with the real worker, by failure mode: the test
email's run input differs from a mailbox run's (a key missing or extra, attachments without their name, type or size,
no body file); it does not reach the human task the mailbox run reaches; the run does not say who sent it and how; an
attachment the team's Files does not hold is sent anyway. The mailbox run comes from the listener reading the fixture
levy notice; the test email from the start adapter `POST /v1/runs/start` calls, with the same PDF already in Files as
the console's upload leaves it. Files is faked at its documented API, so the real FilesClient runs."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api import run_starts
from ops_agents.api.auth import Principal
from ops_agents.api.email_trigger import Bound, EmailTriggers, binding_of
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.leases import Leases
from ops_agents.store.tenancy import tenant_scope
from ops_email.testing import FileMailSource, fake_folder
from ops_engine.definition import WorkflowDefinition, parse
from ops_engine.shapes import EMAIL
from ops_engine.store import DefinitionStore, RunStore
from ops_files_client import FilesClient
from ops_identity import ServiceClient, dev_service_signer
from ops_service_kit.errors import Unprocessable
from tests.engine.test_email_trigger import MAILBOX, NOTICE, PDF, TEAM, FakeFiles, connect, mail
from tests.engine.test_worker import CountingTools, drain, worker

CLERK = Principal(
    name="Clerk", email="clerk.tester@harborpine.example", team_id=TEAM, tenant_id="local", team_ids=(TEAM,), dev=True
)


def intake(mailbox: str) -> WorkflowDefinition:
    """The court order notice's intake: an email arrives with the notice in `mailbox`, and a person checks it."""
    return parse(
        {
            "schemaVersion": 2,
            "id": "notice_intake",
            "nodes": [
                {
                    "id": "start",
                    "type": "ops.trigger.email",
                    "typeVersion": 1,
                    "parameters": {"mailbox": mailbox, "folder": "inbox", "hasAttachment": True},
                },
                {
                    "id": "check",
                    "type": "ops.flow.humanReview",
                    "typeVersion": 1,
                    "name": "Check the court order notice",
                    "parameters": {"title": "Check the court order notice"},
                },
                {"id": "ok", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "checked"}},
                {"id": "no", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "refused"}},
            ],
            "connections": [
                {"from": {"node": "start", "port": "payload"}, "to": {"node": "check", "port": "in"}},
                {"from": {"node": "check", "port": "approve"}, "to": {"node": "ok", "port": "in"}},
                {"from": {"node": "check", "port": "reject"}, "to": {"node": "no", "port": "in"}},
            ],
        }
    )


class Files(FakeFiles):
    """files-service's store, read by id and content as well: what the console's upload left and the adapter reads."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        found = re.fullmatch(r"/v1/files/([^/]+)(/content)?", request.url.path)
        if request.method == "GET" and found:
            row = next((r for r in self.stored.values() if r["id"] == found.group(1)), None)
            if row is None:
                return httpx.Response(404, json={"success": False, "error": {"code": "not_found", "message": "File"}})
            if found.group(2):
                if row["scan"]["status"] != "clean":  # files-service hands over a clean file's bytes only
                    error = {"code": "not_clean", "message": "The file has not passed its scan."}
                    return httpx.Response(423, json={"success": False, "error": error})
                return httpx.Response(200, content=row["bytes"], headers={"content-type": row["mime"]})
            return httpx.Response(200, json={"success": True, "data": {k: v for k, v in row.items() if k != "bytes"}})
        return super().__call__(request)


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


def files_client(files: Files) -> FilesClient:
    http = httpx.AsyncClient(base_url="http://files", transport=httpx.MockTransport(files))
    return FilesClient(ServiceClient(http, dev_service_signer(), "agents", "files"))


async def live_intake(engine: AsyncEngine, tenant: str, mailbox: str = MAILBOX) -> dict[str, Any]:
    d = intake(mailbox)
    store = DefinitionStore(EngineTransactions(engine))
    with tenant_scope(tenant):
        version, _ = await store.publish(
            d.id, name="Court order notices", definition=d.wire(), digest=d.digest(), now="n", by="b",
            team=TEAM,
        )  # fmt: skip
        await store.go_live(d.id, version)
        row = await store.get(d.id, version, team=TEAM)
    assert row is not None
    return row


async def by_mailbox(engine: AsyncEngine, tenant: str, row: dict[str, Any], files: Files, inbox: Path) -> str:
    """The listener's run for the fixture notice: a first pass takes the cursor, the notice arrives, a second starts."""
    with tenant_scope(tenant):
        mailbox = await connect(engine, tenant, inbox.name)
    listener = EmailTriggers(
        engine,
        lambda m, folder: FileMailSource(fake_folder(inbox.parent, m.address, folder)),
        files_client(files),
        Leases(engine, owner=f"poll-{uuid4().hex[:6]}", ttl=30),
    )
    binding = binding_of(row["definition"])
    assert binding is not None
    bound = Bound(row, binding, mailbox)
    with tenant_scope(tenant):
        assert (await listener.poll(bound)).first_sync
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "msg-1.json").write_text(json.dumps(mail(1)))
        [run_id] = (await listener.poll(bound)).started
    return run_id


async def by_test_email(engine: AsyncEngine, tenant: str, row: dict[str, Any], files: Files, ids: list[str]) -> str:
    rt: Any = SimpleNamespace(db=engine, start_files=files_client(files))
    values = {
        "from": NOTICE["from"]["emailAddress"]["address"],
        "subject": NOTICE["subject"],
        "body": NOTICE["body"]["content"],
        "attachments": [{"fileId": i, "name": "levy_notice.pdf"} for i in ids],
    }
    with tenant_scope(tenant):
        run = await run_starts.start(rt, CLERK, row, values, "live")
    return str(run["id"])


async def uploaded(files: Files, tenant: str) -> str:
    """The notice as the console's upload leaves it before the email is sent: an Email attachment in Files."""
    with tenant_scope(tenant):
        stored = await files_client(files).write(
            tenant, TEAM, PDF, name=NOTICE["attachments"][0]["name"], mime="application/pdf",
            purpose="case_attachment", uploaded_by=CLERK.email, idempotency_key="console-upload",
        )  # fmt: skip
    return stored.file.id


def shape(value: dict[str, Any]) -> dict[str, Any]:
    """A run input with each stored file's id left out: what must be equal between the two ways in."""
    out = {k: v for k, v in value.items() if k not in {"messageId", "receivedAt"}}
    attachments = cast(list[dict[str, Any]], value["attachments"])
    out["attachments"] = [{k: v for k, v in a.items() if k != "fileId"} for a in attachments]
    body = cast(dict[str, Any], value["bodyFile"] or {})
    out["bodyFile"] = {k: v for k, v in body.items() if k != "fileId"}
    return out


async def test_a_test_email_runs_with_the_input_and_steps_a_mailbox_email_gets(
    engine: AsyncEngine, tmp_path: Path
) -> None:
    tenant, files, address = f"t-{uuid4().hex[:8]}", Files(), f"levy-{uuid4().hex[:8]}@bank.example"
    row = await live_intake(engine, tenant, address)
    mailed = await by_mailbox(engine, tenant, row, files, tmp_path / address)
    sent = await by_test_email(engine, tenant, row, files, [await uploaded(files, tenant)])
    runs = RunStore(EngineTransactions(engine))
    with tenant_scope(tenant):
        a, b = await runs.get(mailed), await runs.get(sent)
    assert a is not None and b is not None
    assert set(a["input"]) == set(b["input"]) == set(EMAIL["required"]), (a["input"], b["input"])
    assert shape(a["input"]) == shape(b["input"]), (shape(a["input"]), shape(b["input"]))
    [attachment] = b["input"]["attachments"]
    assert attachment["size"] == len(PDF) and attachment["mime"] == "application/pdf"
    assert b["input"]["bodyFile"]["name"] == "email-body.txt" and b["input"]["mailbox"] == address
    # Who started each, and how: the mailbox, or the person through the test email form.
    assert a["created_by"] == f"trigger:email:{address}" and a["started_via"] is None
    assert (b["created_by"], b["started_via"]) == (CLERK.email, "start:email")
    assert b["run_key"].startswith("email:") and b["run_key"] != a["run_key"]

    await drain(worker(engine, CountingTools(), InMemorySaver()))
    with tenant_scope(tenant):
        a, b = await runs.get(mailed), await runs.get(sent)
        steps = [[(s["node_id"], s["status"], s["port"]) for s in await runs.steps(r)] for r in (mailed, sent)]
    assert a is not None and b is not None
    # Both wait on the same human task, having taken the same steps to it.
    assert (a["status"], a["waiting"]["node"]) == (b["status"], b["waiting"]["node"]) == ("waiting", "check")
    assert steps[0] == steps[1] and steps[0], steps


async def test_an_attachment_the_teams_files_do_not_hold_is_refused(engine: AsyncEngine) -> None:
    tenant, files = f"t-{uuid4().hex[:8]}", Files()
    row = await live_intake(engine, tenant)
    with pytest.raises(Unprocessable) as refused:
        await by_test_email(engine, tenant, row, files, ["fil_someone_elses"])
    assert refused.value.code == "attachment_not_found"
    with tenant_scope(tenant):
        assert await RunStore(EngineTransactions(engine)).list(workflow_id=row["workflow_id"]) == []


async def test_an_attachment_not_scanned_clean_is_refused(engine: AsyncEngine) -> None:
    tenant, files = f"t-{uuid4().hex[:8]}", Files()
    row = await live_intake(engine, tenant)
    notice = await uploaded(files, tenant)
    next(r for r in files.stored.values() if r["id"] == notice)["scan"] = {"status": "pending"}
    with pytest.raises(Unprocessable) as refused:
        await by_test_email(engine, tenant, row, files, [notice])
    assert refused.value.code == "attachment_not_clean"
    with tenant_scope(tenant):
        assert await RunStore(EngineTransactions(engine)).list(workflow_id=row["workflow_id"]) == []


async def test_a_test_email_the_trigger_filters_would_skip_starts_nothing(engine: AsyncEngine) -> None:
    tenant, files = f"t-{uuid4().hex[:8]}", Files()
    row = await live_intake(engine, tenant)  # hasAttachment: an email without one is skipped
    with pytest.raises(Unprocessable) as refused:
        await by_test_email(engine, tenant, row, files, [])
    assert refused.value.code == "email_filtered" and refused.value.details == {"failed": "hasAttachment"}
