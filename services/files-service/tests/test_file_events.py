"""files-service's service events (c-250), by failure mode: a deletion whose file.deleted is lost, so documents-service
keeps what it read from a file that is gone (F4, F5); an event for a deletion that did not happen (F4); a read request
started twice by a repeated click, run by someone who may not change files, or whose run the console cannot follow
(F2)."""

from __future__ import annotations

from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_files.store.event_relay import sender
from ops_files.store.files import service_outbox
from ops_files.store.read_requests import ReadRequestsStore
from ops_store.outbox import Relay
from tests import test_api
from tests.test_api import OPS, PDF, Client, _data, _upload  # pyright: ignore[reportPrivateUsage]

# The files tests' app fixture, defined beside the API tests.
client = test_api.client


async def events(engine: AsyncEngine, tenant: str) -> list[dict[str, object]]:
    async with engine.connect() as c:
        rows = await c.execute(sa.select(service_outbox).where(service_outbox.c.tenant_id == tenant))
        return [dict(r) for r in rows.mappings()]


async def test_a_deleted_file_reports_file_deleted_and_a_refused_delete_reports_nothing(
    client: Client, engine: AsyncEngine, tenant: str
) -> None:
    async with client() as c:
        ticket = await _upload(c)
        fid = _data(await c.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS))["file"]["id"]
        kept = await _upload(c, PDF + b"\n% kept", name="kept.pdf")
        kept_id = _data(await c.post(f"/v1/files/uploads/{kept['fileId']}/complete", headers=OPS))["file"]["id"]
        deleted = await c.delete(f"/v1/files/{fid}", headers=OPS)
    async with client(role="chat_user") as chatter:
        refused = await chatter.delete(f"/v1/files/{kept_id}", headers=OPS)
    [event] = await events(engine, tenant)
    assert deleted.status_code == 204 and refused.status_code == 403, (deleted.text, refused.text)
    assert (event["name"], event["event_key"], event["team_id"], event["sent_at"]) == (
        "file.deleted",
        fid,
        "team_ops",
        None,
    )
    payload = cast(dict[str, Any], event["payload"])
    assert (payload["fileId"], payload["name"], payload["deletedBy"]) == (fid, "s.pdf", "james@northfieldbank.com")
    assert payload["digest"], payload


class Agents:
    """agents-service's POST /v1/events, answering the run a read request's event started."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def post(self, path: str, body: dict[str, Any], **kw: Any) -> dict[str, Any]:
        self.sent.append(body)
        return {"status": "started", "runIds": ["wfrun_1"]}


async def test_a_read_request_is_one_request_per_key_and_names_its_run_once_delivered(
    client: Client, engine: AsyncEngine, tenant: str
) -> None:
    ask = {"documentTypeId": "restraining_notice", "typeName": "Restraining notice"}
    key = {**OPS, "Idempotency-Key": "k1"}
    async with client() as c:
        ticket = await _upload(c)
        fid = _data(await c.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS))["file"]["id"]
        posted = await c.post(f"/v1/files/{fid}/read-requests", json=ask, headers=key)
        assert posted.status_code == 202, posted.text
        first = _data(posted)
        again = _data(await c.post(f"/v1/files/{fid}/read-requests", json=ask, headers=key))
        agents = Agents()
        await Relay(engine, service_outbox, sender(agents, ReadRequestsStore(engine))).once()  # type: ignore[arg-type]
        followed = _data(await c.get(f"/v1/files/{fid}/read-requests/{first['key']}", headers=OPS))
    async with client(role="chat_user") as chatter:
        refused = await chatter.post(f"/v1/files/{fid}/read-requests", json=ask, headers=OPS)
    assert again["key"] == first["key"] and (first["status"], first["runId"]) == ("queued", None), again
    # The relay delivers every due event in the outbox, other tests' included; this request's is the one keyed by it.
    [event] = [e for e in agents.sent if e["key"] == first["key"]]
    assert (event["name"], event["key"], event["actor"]) == ("file.read_requested", first["key"], first["requestedBy"])
    assert event["payload"]["documentTypeId"] == "restraining_notice" and event["payload"]["fileId"] == fid
    assert (followed["status"], followed["runId"]) == ("started", "wfrun_1"), followed
    assert refused.status_code == 403, refused.text


async def test_a_read_request_with_no_type_asks_for_detect_and_a_read_with_no_type_is_saved_as_not_recognised(
    client: Client, engine: AsyncEngine
) -> None:
    """c-335: the Files page reads a file without choosing its type; the request and its event carry no type, and what
    a Detect read that found none of the team's types saves has no type or version."""
    async with client() as c:
        ticket = await _upload(c)
        fid = _data(await c.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS))["file"]["id"]
        posted = await c.post(f"/v1/files/{fid}/read-requests", json={}, headers={**OPS, "Idempotency-Key": "d1"})
        agents = Agents()
        await Relay(engine, service_outbox, sender(agents, ReadRequestsStore(engine))).once()  # type: ignore[arg-type]
        unread = {"path": "model", "fieldsToCheck": 0, "extractionId": "ext_9", "readAt": "2026-10-19T12:00:00Z"}
        saved = await c.put(f"/v1/files/{fid}/data", json=unread, headers=OPS)
    assert posted.status_code == 202 and _data(posted)["documentTypeId"] is None, posted.text
    [event] = [e for e in agents.sent if e["key"] == _data(posted)["key"]]
    assert event["payload"]["documentTypeId"] is None, event
    assert saved.status_code == 200, saved.text
    data = _data(saved)["data"]
    assert (data["typeId"], data["version"], data["extractionId"]) == (None, None, "ext_9"), data
