"""uc-668, api layer: docs/usecases/tools-service/meeting-log-saves-both-or-neither.md, story S1 (steps 1-3).
platform-service signs the seeded people in; tools-service runs with plugins on and the Salesforce plugin from
ops-ai-plugins (OPS_SALESFORCE_PLUGIN names another checkout of it); the fake Salesforce holds Dana Whitfield's advisor
org. Each call is a gateway write as agents-service makes it for a run. No model call."""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fake_salesforce import EDUCATION_ID, GRACE_ID, salesforce
from steps import required
from usecase_harness import PLUGINS_REPO
from usecase_harness import (
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    bearer,
    check,
    data,
    finish,
    platform,
    service_headers,
    signed_in,
    tools,
)

PLUGIN = "opsai.salesforce"
AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
SALESFORCE = Path(
    os.environ.get("OPS_SALESFORCE_PLUGIN")
    or PLUGINS_REPO / "plugins/salesforce/src/ops_plugin_salesforce"
)
PLUGINS = {"OPS_PLUGINS": "true", "OPS_PLUGIN_PATHS": json.dumps([str(SALESFORCE)])}
TENANT: dict[str, str] = {}
NOTE = "Grace Okafor wants to add $25,000 to the education savings plan. Agreed to move to proposal."


def save(gw: httpx.Client, records: list[dict[str, Any]]) -> httpx.Response:
    """One save_records call as agents-service makes it for a run in team_ops."""
    headers = service_headers("tools", tenant=TENANT["id"], service="agents", team="team_ops")
    body = {"tool": "salesforce_save_records", "input": {"records": records}, "key": uuid4().hex}
    return gw.post("/v1/calls", json={**body, "runContext": {"environment": "live"}}, headers=headers)


def opportunity(stage: str, amount: int) -> dict[str, Any]:
    return {"object": "Opportunity", "id": EDUCATION_ID, "fields": {"StageName": stage, "Amount": amount}}


def task(**fields: Any) -> dict[str, Any]:
    base = {"Subject": "Meeting with Grace Okafor", "WhatId": EDUCATION_ID, "WhoId": GRACE_ID, "Status": "Completed"}
    return {"object": "Task", "fields": {**base, "Description": NOTE, **fields}}


with ExitStack() as stack:
    sf = stack.enter_context(salesforce())
    api, _ = stack.enter_context(platform())
    gw = stack.enter_context(
        tools({**sf["settings"], **AUTH, **PLUGINS, "OPS_CONSOLE_URL": "https://console.acme.test"})
    )
    sam = bearer(signed_in(api, "s.adeyemi@harborpine.example"), "team_security")
    priya_session = signed_in(api, "p.shah@harborpine.example")
    priya = bearer(priya_session, "team_ops")
    TENANT["id"] = str((priya_session.get("principal") or {}).get("tenantId") or priya_session.get("tenantId") or "")
    fake = sf["fake"]

    # Set-up as uc-581's: Salesforce's hosts, the team switch, and the team signed in as Dana with write access.
    for h in sf["hosts"]:
        gw.post("/v1/egress/hosts", json={"value": h, "note": "uc-668"}, headers=sam)
    gw.post("/v1/egress/ranges", json={"value": sf["range"], "note": "uc-668"}, headers=sam)
    own = {
        "app": f"plugin:{PLUGIN}",
        "clientId": "ops-ai-acme",
        "clientSecret": "s3",
        "settings": {"login_url": sf["login_url"]},
    }
    credential = (required(gw.post("/v1/app-credentials", json=own, headers=priya), "/v1/app-credentials")).get("id")
    turned = gw.put(f"/v1/apps/plugin:{PLUGIN}/team", json={"enabled": True, "credentialId": credential}, headers=priya)
    connection_id = str((data(turned) or {}).get("connectionId") or "con_missing")
    started = gw.post(f"/v1/apps/plugin:{PLUGIN}/accounts/{connection_id}/sign-in", json={}, headers=priya)
    back = sf["sign_in"]((data(started) or {}).get("authorizeUrl", ""), "dana.whitfield")
    done = gw.post(
        "/v1/sign-ins/complete", json={"state": back.get("state", ""), "code": back.get("code", "")}, headers=priya
    )
    # A new app has every tool on; adding the write again is how an admin restores one turned off.
    added = gw.post(f"/v1/apps/plugin:{PLUGIN}/tools", json={"tools": ["salesforce_save_records"]}, headers=priya)
    check(
        "setup: Salesforce is on for the team, signed in as Dana, with Save records together added",
        turned.status_code == 200 and done.status_code == 200 and added.status_code == 200,
        {"turned": turned.text[:200], "done": done.text[:200], "added": added.text[:200]},
    )
    tasks_before = len(fake.records.get("Task", {}))

    # 1. A meeting log is one call: the opportunity changes and its Task is made, in one composite request.
    composites = len([e for e in fake.edits if e.get("op") in ("create", "update")])
    first = save(gw, [opportunity("Proposal", 75000), task()])
    out = dict((data(first) or {}).get("output") or {})
    edu = fake.records["Opportunity"][EDUCATION_ID]
    made = [t for t in fake.records.get("Task", {}).values() if t.get("Description") == NOTE]
    check(
        "1 one call updates the opportunity and makes the meeting's Task on it",
        first.status_code == 200
        and [s.get("action") for s in out.get("saved", [])] == ["updated", "created"]
        and edu.get("StageName") == "Proposal"
        and edu.get("Amount") == 75000
        and len(made) == 1
        and made[0].get("WhatId") == EDUCATION_ID
        and len(fake.records["Task"]) == tasks_before + 1,
        {"status": first.status_code, "out": out, "stage": edu.get("StageName"), "text": first.text[:300]},
    )

    # 2. A Task Salesforce refuses (a date it cannot read) leaves the opportunity as it was: nothing is saved.
    before = dict(fake.records["Opportunity"][EDUCATION_ID])
    tasks_now = len(fake.records["Task"])
    second = save(gw, [opportunity("Negotiation", 90000), task(ActivityDate="next Friday")])
    after = fake.records["Opportunity"][EDUCATION_ID]
    check(
        "2 Salesforce refused the save, not the gateway",
        "Nothing was saved" in second.text and "TOOL_NOT_ADDED" not in second.text,
        {"status": second.status_code, "text": second.text[:300]},
    )
    check(
        "2 the opportunity and the Tasks are as they were before the refused save",
        after.get("StageName") == before.get("StageName") == "Proposal"
        and after.get("Amount") == 75000
        and len(fake.records["Task"]) == tasks_now,
        {"stage": after.get("StageName"), "amount": after.get("Amount"), "tasks": len(fake.records["Task"])},
    )

    # 3. The refusal names the field Salesforce refused, so the review card can mark it.
    said = second.text
    check(
        "3 the refusal says nothing was saved and names the refused field",
        "Nothing was saved" in said and "ActivityDate" in said and "PROCESSING_HALTED" not in said,
        said[:400],
    )

finish()
