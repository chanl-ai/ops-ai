"""Schedule routes, by failure mode: a bad rule is saved (under the floor, no day, a window ending before it starts, an
unknown zone or kind); every tick would fail on an input field the clock cannot fill; the kinds route or the preview
disagrees with what a save stores. Through the real app and database."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from httpx import AsyncClient

JAMES = {"X-Dev-User": "j.richardson@harborpine.example"}


def definition(wid: str, schema: dict[str, Any] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"inputSchema": schema} if schema else {}
    return {
        "schemaVersion": 2,
        "id": wid,
        "name": "Held wires",
        "nodes": [
            {"id": "start", "type": "ops.trigger.schedule", "typeVersion": 1, "name": "Sched", "parameters": params},
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {}},
        ],
        "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
    }


async def saved(client: AsyncClient, schema: dict[str, Any] | None = None) -> str:
    wid = f"wf_{uuid4().hex[:8]}"
    res = await client.post("/v1/workflows/definitions", json={"definition": definition(wid, schema)}, headers=JAMES)
    assert res.status_code < 300, res.text
    return wid


def url(wid: str) -> str:
    return f"/v1/workflows/definitions/{wid}/triggers/start/schedule"


async def test_a_bad_rule_or_a_field_the_clock_cannot_fill_is_refused_naming_it(client: AsyncClient) -> None:
    wid = await saved(client)
    every: dict[str, Any] = {"kind": "every", "unit": "minutes", "every": 15}
    cases: list[tuple[dict[str, Any], str]] = [
        (every | {"every": 2}, "every"),
        (every | {"days": []}, "days"),
        (every | {"between": ["18:00", "07:00"]}, "between"),
        (every | {"tz": "Mars/Phobos"}, "tz"),
    ]
    for bad, field in cases:
        res = await client.put(url(wid), json={"rule": bad}, headers=JAMES)
        assert res.status_code == 422, res.text
        assert res.json()["error"]["details"]["field"] == field, bad
    unknown = await client.put(url(wid), json={"rule": {"kind": "cron", "line": "* * * * *"}}, headers=JAMES)
    assert unknown.status_code == 422 and "every" in unknown.json()["error"]["details"]["known"]

    needs_day = await saved(client, {"type": "object", "required": ["day"], "properties": {"day": {}}})
    refused = await client.put(url(needs_day), json={"rule": every}, headers=JAMES)
    assert refused.status_code == 422 and refused.json()["error"]["details"]["field"] == "day", refused.text
    assert (await client.get(url(needs_day), headers=JAMES)).status_code == 404


async def test_kinds_preview_and_save_agree_and_a_save_needs_no_publish(client: AsyncClient) -> None:
    kinds = (await client.get("/v1/schedules/kinds", headers=JAMES)).json()["data"]
    every = next(k for k in kinds if k["name"] == "every")
    assert every["schema"]["properties"]["kind"] == {"const": "every"}

    wid = await saved(client)
    rule = {"kind": "every", "every": 15, "unit": "minutes", "start": "07:00", "tz": "Europe/London"}
    preview = (await client.post("/v1/schedules/preview", json={"rule": rule}, headers=JAMES)).json()["data"]
    res = await client.put(url(wid), json={"rule": rule}, headers=JAMES)
    assert res.status_code == 200, res.text
    stored = res.json()["data"]
    assert stored["rule"] == preview["rule"] and stored["words"] == preview["words"] == (
        "Every 15 minutes from 07:00, Europe/London"
    )
    assert len(stored["nextRuns"]) == 3 and stored["changedBy"]
    assert (await client.get(url(wid), headers=JAMES)).json()["data"]["rule"] == stored["rule"]
    assert (await client.delete(url(wid), headers=JAMES)).status_code == 204
    assert (await client.get(url(wid), headers=JAMES)).status_code == 404


async def test_publishing_a_version_the_saved_schedule_cannot_fill_is_refused(client: AsyncClient) -> None:
    wid = await saved(client)
    put = await client.put(url(wid), json={"rule": {"kind": "every", "every": 15, "unit": "minutes"}}, headers=JAMES)
    assert put.status_code == 200, put.text
    shown = (await client.get(f"/v1/workflows/definitions/{wid}", headers=JAMES)).json()["data"]
    assert [s["words"] for s in shown["schedules"]] == ["Every 15 minutes from 00:00, UTC"]

    schema: dict[str, Any] = {"type": "object", "required": ["day"], "properties": {"day": {}}}
    v2 = await client.post("/v1/workflows/definitions", json={"definition": definition(wid, schema)}, headers=JAMES)
    assert v2.status_code < 300, v2.text
    asked = await client.post(
        f"/v1/workflows/definitions/{wid}/publish-requests",
        json={"version": v2.json()["data"]["version"]},
        headers=JAMES,
    )
    assert asked.status_code == 422, asked.text
    assert asked.json()["error"]["code"] == "schedule_input_required"
    assert asked.json()["error"]["details"]["field"] == "day"
