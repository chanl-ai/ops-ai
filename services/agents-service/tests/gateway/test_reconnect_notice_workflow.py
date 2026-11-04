"""An app's team account that stopped working tells the team's admins in Human Tasks, through the real event
route, worker and Human Tasks, as tools-service's relay reports it. By failure mode: the event has no handler and is
recorded unhandled, so nobody is told; the task does not say which app, what the system said or where to fix it; and
the task cannot be closed once the account is reconnected."""

from __future__ import annotations

from uuid import uuid4

import httpx

from ops_engine.worker import Worker

from .test_engine_reviewed_write import (  # noqa: F401
    REVIEWER,
    finish,
    stack,  # pyright: ignore[reportUnusedImport]
)
from .test_tool_access_workflow import TEAM, tools_service

EVENT = "app_account.needs_reconnect"


async def test_a_broken_team_account_asks_an_admin_to_reconnect_its_app(
    stack: tuple[httpx.AsyncClient, Worker],  # noqa: F811
) -> None:
    client, worker = stack
    key = f"ca_{uuid4().hex[:8]}:production:refused:2:-"
    payload = {
        "connectionId": key.split(":", 1)[0],
        "app": "Client desk",
        "pluginId": "test.client",
        "environment": "production",
        "state": "refused",
        "reason": "login.multi.test refused the sign-in (invalid_client).",
        "at": "2026-11-01T09:00:00+00:00",
    }
    r = await client.post(
        "/v1/events",
        json={"name": EVENT, "key": key, "teamId": "team_ops", "payload": payload},
        headers=tools_service(),
    )
    assert r.status_code == 202 and r.json()["data"]["status"] == "started", r.text
    [run_id] = r.json()["data"]["runIds"]
    assert (await finish(worker, client, run_id))["status"] == "waiting"

    sheet = await client.get(f"/reviews/by-run-key/{EVENT}:{key}", headers=REVIEWER | TEAM)
    assert sheet.status_code == 200, sheet.text
    review = sheet.json()["data"]
    assert review["title"] == "Reconnect Client desk's team account", review["title"]
    task = review["task"]
    assert task["type"]["id"] == "app_reconnect", task["type"]
    said = next(x["data"]["text"] for x in task["regions"] if x["region"] == "message")
    assert "invalid_client" in said and "under Apps" in said, said
    facts = next(x["data"]["facts"] for x in task["regions"] if x["region"] == "facts")
    assert {f["label"]: f["value"] for f in facts} == {
        "App": "Client desk",
        "Environment": "production",
        "State": "refused",
    }, facts
    assert [a["label"] for a in task["actions"]] == ["Reconnected", "Dismiss"], task["actions"]

    done = await client.post(f"/reviews/{run_id}/decision", json={"decision": "approve"}, headers=REVIEWER | TEAM)
    assert done.status_code == 200, done.text
    assert (await finish(worker, client, run_id))["outcome"] == "reconnected"
