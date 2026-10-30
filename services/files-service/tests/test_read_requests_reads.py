"""A Files page read without a document type (c-535), by failure mode: the read choice, hint or page limit dropped
between the read request and the event that starts the system extract workflow, so the person asked for the full text
or proposed fields and got a Detect read; an unknown read accepted."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_files.store.event_relay import sender
from ops_files.store.files import service_outbox
from ops_files.store.read_requests import ReadRequestsStore
from ops_store.outbox import Relay
from tests import test_api
from tests.test_api import OPS, Client, _data, _upload  # pyright: ignore[reportPrivateUsage]
from tests.test_file_events import Agents

client = test_api.client


async def test_a_read_request_carries_its_read_hint_and_page_limit_to_the_event(
    client: Client, engine: AsyncEngine
) -> None:
    async with client() as c:
        ticket = await _upload(c)
        fid = _data(await c.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS))["file"]["id"]
        ask = {"read": "propose", "hint": "a supplier invoice", "maxPages": 4}
        posted = await c.post(f"/v1/files/{fid}/read-requests", json=ask, headers={**OPS, "Idempotency-Key": "p1"})
        unknown = await c.post(
            f"/v1/files/{fid}/read-requests", json={"read": "everything"}, headers={**OPS, "Idempotency-Key": "p2"}
        )
        agents = Agents()
        await Relay(engine, service_outbox, sender(agents, ReadRequestsStore(engine))).once()  # type: ignore[arg-type]
    assert posted.status_code == 202, posted.text
    [event] = [e for e in agents.sent if e["key"] == _data(posted)["key"]]
    payload = event["payload"]
    assert (payload["read"], payload["hint"], payload["maxPages"]) == ("propose", "a supplier invoice", 4), payload
    assert unknown.status_code == 400 and "read" in unknown.json()["error"]["message"], unknown.text
