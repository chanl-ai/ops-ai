"""What was read from a file (c-250), by failure mode: the files list needing another call per row to say what a file
was read as, or unable to filter by it (F1); a caller who may not change the team's files recording data, or a
service without files:edit (F2); data recorded on another team's file (F3)."""

from __future__ import annotations

from typing import Any

import httpx

from tests import test_api
from tests.test_api import OPS, PDF, Client, _data, _kb, _upload  # pyright: ignore[reportPrivateUsage]

# The files tests' app fixture, defined beside the API tests.
client = test_api.client

READ = {
    "typeId": "restraining_notice",
    "typeName": "Restraining notice",
    "version": 2,
    "path": "model",
    "fieldsToCheck": 3,
    "extractionId": "ext_0123456789abcdef",
    "readAt": "2026-10-18T23:40:00Z",
}


async def stored(c: httpx.AsyncClient, body: bytes = PDF, name: str = "notice.pdf") -> str:
    ticket = await _upload(c, body, name=name)
    return str(_data(await c.post(f"/v1/files/uploads/{ticket['fileId']}/complete", headers=OPS))["file"]["id"])


async def test_the_list_carries_and_filters_what_each_file_was_read_as(client: Client) -> None:
    async with client() as c:
        read, other = await stored(c), await stored(c, PDF + b"\n% second", "other.pdf")
        put = await c.put(f"/v1/files/{read}/data", json=READ, headers=OPS)
        listed: dict[str, Any] = _data(await c.get("/v1/files", headers=OPS))
        model = _data(await c.get("/v1/files", params={"readPath": "model"}, headers=OPS))
        typed = _data(await c.get("/v1/files", params={"readAs": "levy_notice"}, headers=OPS))
    assert put.status_code == 200 and _data(put)["data"]["typeId"] == "restraining_notice", put.text
    rows = {r["id"]: r for r in listed["data"]}
    assert rows[read]["data"]["fieldsToCheck"] == 3 and rows[read]["data"]["typeName"] == "Restraining notice", rows
    assert rows[other]["data"] is None
    assert [r["id"] for r in model["data"]] == [read] and typed["data"] == []
    assert listed["facets"]["readAs"] == {"restraining_notice": 1, "None": 1}, listed["facets"]


async def test_only_a_caller_who_may_change_files_records_data(client: Client, tenant: str) -> None:
    async with client() as builder:
        fid = await stored(builder)
    # TODO(c-250): the person path goes once the extract workflow's setData step writes it; until then a member
    # without files.create (a chat-only member) is refused.
    async with client(role="chat_user") as chatter:
        refused = await chatter.put(f"/v1/files/{fid}/data", json=READ, headers=OPS)
    async with client() as c:
        viewer = await c.put(f"/v1/files/{fid}/data", json=READ, headers=_kb(tenant, "team_ops", ["files:view"]))
        service = await c.put(f"/v1/files/{fid}/data", json=READ, headers=_kb(tenant, "team_ops", ["files:edit"]))
    assert (refused.status_code, refused.json()["error"]["code"]) == (403, "role_required"), refused.text
    assert viewer.status_code == 403 and service.status_code == 200, (viewer.text, service.text)


async def test_data_on_another_teams_file_is_not_found(client: Client) -> None:
    async with client() as c:
        fid = await stored(c)
        theirs = await c.put(f"/v1/files/{fid}/data", json=READ, headers={"X-Team-Id": "team_cards"})
    assert theirs.status_code == 404, theirs.text
