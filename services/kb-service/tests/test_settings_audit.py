"""Settings changes reach the account's one audit log, by failure mode: a change that leaves no entry, an entry that
names neither the fields nor their values, a save that changed nothing still logged, and an entry delivered again
after it was sent."""

from __future__ import annotations

import json
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import ServiceClient, dev_service_signer
from ops_kb.store.event_relay import relay
from ops_store.audit import AUDIT_ROUTE

from .test_bases_and_sources import data
from .test_sync import file_source


class AuditLog:
    """platform-service's audit intake as kb-service's relay calls it: every body posted, by entry id."""

    def __init__(self) -> None:
        self.posted: list[dict[str, Any]] = []

    def client(self) -> ServiceClient:
        def handle(request: httpx.Request) -> httpx.Response:
            assert request.url.path == AUDIT_ROUTE
            body = json.loads(request.content)
            self.posted.append(body)
            return httpx.Response(200, json={"success": True, "data": {"id": body["key"], "written": True}})

        http = httpx.AsyncClient(transport=httpx.MockTransport(handle), base_url="http://platform-internal")
        return ServiceClient(http, dev_service_signer(), "kb", "platform", ["audit:create"])

    def about(self, target_id: str) -> list[dict[str, Any]]:
        return [b for b in self.posted if b["payload"]["targetId"] == target_id]


async def test_a_source_settings_change_is_one_entry_naming_each_field_before_and_after(
    engine: AsyncEngine, client: httpx.AsyncClient
) -> None:
    src = await file_source(client)
    patched = await client.patch(f"/v1/sources/{src['id']}", json={"name": "Lending policy PDFs", "tags": ["policy"]})
    assert patched.status_code == 200, patched.text
    log = AuditLog()
    await relay(engine, log.client()).once()
    [entry] = log.about(src["id"])
    assert (entry["name"], entry["payload"]["action"]) == ("audit.recorded", "knowledge.source.settings")
    assert entry["actor"] and "teamId" not in entry
    detail = entry["payload"]["detail"]
    assert detail["changes"] == {
        "name": {"from": "Lending PDFs", "to": "Lending policy PDFs"},
        "tags": {"from": [], "to": ["policy"]},
    }
    assert detail["summary"] == "Changed the settings of source Lending PDFs: name, tags"


async def test_a_base_retrieval_change_names_only_the_keys_that_moved(
    engine: AsyncEngine, client: httpx.AsyncClient
) -> None:
    body = {"name": "Claims", "owner": "james@harborpine.example"}
    kb = data(await client.post("/v1/knowledge-bases", json=body), 201)
    patch = {"retrieval": {"threshold": 0.6, "chunkLimit": 8}}
    assert (await client.patch(f"/v1/knowledge-bases/{kb['id']}", json=patch)).status_code == 200
    log = AuditLog()
    await relay(engine, log.client()).once()
    [entry] = log.about(kb["id"])
    assert entry["payload"]["detail"]["changes"] == {"retrieval": {"threshold": {"from": 0.5, "to": 0.6}}}


async def test_a_save_that_changes_nothing_logs_nothing_and_a_sent_entry_is_not_sent_again(
    engine: AsyncEngine, client: httpx.AsyncClient
) -> None:
    src = await file_source(client)
    same = await client.patch(f"/v1/sources/{src['id']}", json={"name": "Lending PDFs"})
    assert same.status_code == 200, same.text
    await client.patch(f"/v1/sources/{src['id']}", json={"collection": "Retail lending"})
    log = AuditLog()
    hand_off = relay(engine, log.client())
    await hand_off.once()
    await hand_off.once()
    assert [e["payload"]["detail"]["changes"] for e in log.about(src["id"])] == [
        {"collection": {"from": "Lending", "to": "Retail lending"}}
    ]
