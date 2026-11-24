"""Schedule routes, by failure mode: a bad rule is saved (under the floor, no day, a window ending before it starts, an
unknown zone or kind); every tick would fail on an input field the clock cannot fill; the kinds route or the preview
disagrees with what a save stores; a read skips the workflow view right, or a save the pause and go-live rights; a
workflow no team owns carries one; clear is blocked by a check only a save needs; a schedule whose step is gone is
listed as if it ran; deleting the workflow leaves its rows. Through the real app and database."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.store.engine import EngineTransactions
from ops_agents.store.schedules import WorkflowSchedules
from ops_agents.store.tenancy import tenant_scope
from ops_agents.store.trigger_events import TriggerEvent, TriggerEvents
from ops_engine.store import DefinitionStore
from tests.engine.test_lifecycle_rights import (  # noqa: F401
    BUILDER,
    CHAT_USER,
    NOT_A_WORKFLOW_READER,
    TENANT,
    VIEWER,
    person,
    stack,  # pyright: ignore[reportUnusedImport]
)

JAMES = {"X-Dev-User": "j.richardson@harborpine.example"}


# A builder whose role an admin took the deployments create cell off: may pause, may not put a workflow to work.
NO_GO_LIVE = person("dee", "team_ops", "builder", unticked=(("deployments", "create"),))
EVERY_15: dict[str, Any] = {"kind": "every", "every": 15, "unit": "minutes"}


def definition(wid: str, schema: dict[str, Any] | None = None, step: str = "start") -> dict[str, Any]:
    params: dict[str, Any] = {"inputSchema": schema} if schema else {}
    return {
        "schemaVersion": 2,
        "id": wid,
        "name": "Held wires",
        "nodes": [
            {"id": step, "type": "ops.trigger.schedule", "typeVersion": 1, "name": "Sched", "parameters": params},
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {}},
        ],
        "connections": [{"from": {"node": step, "port": "payload"}, "to": {"node": "done", "port": "in"}}],
    }


async def saved(client: AsyncClient, schema: dict[str, Any] | None = None) -> str:
    wid = f"wf_{uuid4().hex[:8]}"
    res = await client.post("/v1/workflows/definitions", json={"definition": definition(wid, schema)}, headers=JAMES)
    assert res.status_code < 300, res.text
    return wid


def url(wid: str) -> str:
    return f"/v1/workflows/definitions/{wid}/triggers/start/schedule"


async def test_a_bad_rule_is_refused_naming_it_and_kinds_preview_save_and_view_agree(client: AsyncClient) -> None:
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
    floor = await client.put(url(wid), json={"rule": every | {"every": 2}}, headers=JAMES)
    assert floor.json()["error"]["message"] == "At least 5 minutes on this install."
    unknown = await client.put(url(wid), json={"rule": {"kind": "cron", "line": "* * * * *"}}, headers=JAMES)
    assert unknown.status_code == 422 and "every" in unknown.json()["error"]["details"]["known"]

    needs_day = await saved(client, {"type": "object", "required": ["day"], "properties": {"day": {}}})
    refused = await client.put(url(needs_day), json={"rule": every}, headers=JAMES)
    assert refused.status_code == 422 and refused.json()["error"]["details"]["field"] == "day", refused.text
    assert (await client.get(url(needs_day), headers=JAMES)).status_code == 404

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

    wid = await saved(client)  # a second workflow, saved with the default rule
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


async def test_each_route_asks_its_rights_and_clear_needs_nothing_else(stack: tuple[AsyncClient, AsyncEngine]) -> None:  # noqa: F811
    c, engine = stack

    async def made(wid: str, d: dict[str, Any]) -> int:
        res = await c.post("/v1/workflows/definitions", json={"definition": d}, headers=BUILDER)
        assert res.status_code < 300, res.text
        return int(res.json()["data"]["version"])

    await made("needs_day", definition("needs_day"))
    for refused in (NO_GO_LIVE, VIEWER):
        put = await c.put(url("needs_day"), json={"rule": EVERY_15}, headers=refused)
        assert put.status_code == 403, put.text
    assert (await c.put(url("needs_day"), json={"rule": EVERY_15}, headers=BUILDER)).status_code == 200
    for refused in (CHAT_USER, NOT_A_WORKFLOW_READER):
        assert (await c.get(url("needs_day"), headers=refused)).status_code == 403
    assert (await c.get(url("needs_day"), headers=VIEWER)).json()["data"]["idle"] == (
        "No version is live yet; the schedule starts once one is."
    )
    # The newest version now needs an input the clock cannot fill: a save is refused, a clear is not.
    await made("needs_day", definition("needs_day", {"type": "object", "required": ["day"], "properties": {"day": {}}}))
    assert (await c.delete(url("needs_day"), headers=VIEWER)).status_code == 403
    assert (await c.delete(url("needs_day"), headers=BUILDER)).status_code == 204

    # The live version dropped the step: the view says so, and clear still works.
    await made("dropped", definition("dropped"))
    assert (await c.put(url("dropped"), json={"rule": EVERY_15}, headers=BUILDER)).status_code == 200
    v2 = await made("dropped", definition("dropped", step="begin"))
    with tenant_scope(TENANT):
        await DefinitionStore(EngineTransactions(engine)).go_live("dropped", v2)
    shown = (await c.get("/v1/workflows/definitions/dropped", headers=VIEWER)).json()["data"]["schedules"]
    assert [s["idle"] for s in shown] == [
        "The live version has no step start, so this schedule starts nothing until one does."
    ]
    with tenant_scope(TENANT):
        await DefinitionStore(EngineTransactions(engine)).set_paused("dropped", True)
    shown = (await c.get("/v1/workflows/definitions/dropped", headers=VIEWER)).json()["data"]["schedules"]
    assert [s["idle"] for s in shown] == ["The workflow is paused, so the schedule starts nothing until it is resumed."]
    assert (await c.delete(url("dropped"), headers=BUILDER)).status_code == 204

    # A workflow no team owns cannot carry one: its runs would have no team.
    store = DefinitionStore(EngineTransactions(engine))
    with tenant_scope(TENANT):
        version, _ = await store.publish(
            "shared", name="Shared", definition=definition("shared"), digest="s" * 64, now="n", by="seed"
        )
        await store.go_live("shared", version)
    no_team = await c.put(url("shared"), json={"rule": EVERY_15}, headers=BUILDER)
    assert no_team.status_code == 422 and no_team.json()["error"]["code"] == "schedule_needs_team", no_team.text

    # Deleting a draft workflow removes its schedule rows.
    await made("draft", definition("draft"))
    assert (await c.put(url("draft"), json={"rule": EVERY_15}, headers=BUILDER)).status_code == 200
    assert (await c.delete("/v1/workflows/definitions/draft", headers=BUILDER)).status_code == 204
    with tenant_scope(TENANT):
        assert await WorkflowSchedules(engine).for_workflow("draft") == []


async def test_a_schedule_view_names_who_changed_it_why_the_last_slot_did_not_run_and_why_it_is_idle(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    c, engine = stack
    res = await c.post("/v1/workflows/definitions", json={"definition": definition("viewed")}, headers=BUILDER)
    assert res.status_code < 300, res.text
    put = await c.put(url("viewed"), json={"rule": EVERY_15}, headers=BUILDER)
    assert put.status_code == 200, put.text
    saved_view = put.json()["data"]
    assert saved_view["changedByName"] and saved_view["idleCode"] == "no_live_version"
    assert saved_view["lastRunId"] is None and saved_view["lastOutcomeReason"] is None
    # The clock skipped the slot at 10:00: its state is on the row, its reason in the trigger's log.
    with tenant_scope(TENANT):
        row = await WorkflowSchedules(engine).get("viewed", "start")
        assert row is not None
        await WorkflowSchedules(engine).record_slot(
            "viewed", "start", expected=None, slot="2026-11-23T10:00:00Z", outcome="skipped", digest="d", run_id="run_1"
        )
        await TriggerEvents(engine).add(
            TriggerEvent(
                team_id=row.team_id,
                workflow_id="viewed",
                source="schedule:start",
                event_key="schedule:viewed:2026-11-23T10:00Z",
                sender="",
                subject="Every 15 minutes",
                received_at="2026-11-23T10:00:00Z",
                outcome="skipped",
                run_id=None,
                detail={"reason": "The last scheduled run was still going."},
            )
        )
        # Another step of the same workflow logged a reason for the same minute: it is not this schedule's.
        await TriggerEvents(engine).add(
            TriggerEvent(
                team_id=row.team_id,
                workflow_id="viewed",
                source="schedule:other",
                event_key="schedule:viewed:2026-11-23T10:00Z",
                sender="",
                subject="Every hour",
                received_at="2026-11-23T10:00:00Z",
                outcome="refused",
                run_id=None,
                detail={"reason": "another step's reason"},
            )
        )
    got = (await c.get(url("viewed"), headers=BUILDER)).json()["data"]
    assert (got["lastOutcome"], got["lastOutcomeReason"], got["lastRunId"]) == (
        "skipped",
        "The last scheduled run was still going.",
        "run_1",
    )
    shown = (await c.get("/v1/workflows/definitions/viewed", headers=BUILDER)).json()["data"]["schedules"]
    assert shown[0]["lastOutcomeReason"] == got["lastOutcomeReason"]


async def test_zones_are_searched_and_every_zone_listed_saves(client: AsyncClient) -> None:
    first = (await client.get("/v1/schedules/zones", params={"limit": 25}, headers=JAMES)).json()["data"]
    assert len(first["data"]) == 25 and first["nextCursor"] == "25"
    london = (await client.get("/v1/schedules/zones", params={"search": "london"}, headers=JAMES)).json()["data"]
    assert london["data"] == [{"id": "Europe/London", "label": "Europe/London"}] and london["nextCursor"] is None
    wid = await saved(client)
    rule = EVERY_15 | {"tz": london["data"][0]["id"]}
    assert (await client.put(url(wid), json={"rule": rule}, headers=JAMES)).status_code == 200
