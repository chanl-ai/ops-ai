"""uc-512 a step reads what it receives in plain words, api layer: docs/usecases/agents-service/step-sheet-plain-words.md.

James saves and publishes a refund workflow, a worker runs it once, and the sample route lists each earlier step's
fields with the run's values: the amount as given, the customer's email masked. A step added to the working copy since
the version lists its fields at once; a step the copy does not hold says it is not saved yet. No model is called."""

from __future__ import annotations

import secrets
from contextlib import ExitStack
from typing import Any

from usecase_harness import TEAM, agents, check, data, engine_worker, finish, until

TAG = secrets.token_hex(3)
WF = f"uc512_api_{TAG}"


def definition() -> dict[str, Any]:
    return {
        "schemaVersion": 2,
        "id": WF,
        "name": f"Refund check {TAG}",
        "nodes": [
            {
                "id": "start",
                "type": "ops.trigger.request",
                "typeVersion": 1,
                "name": "Refund asked",
                "parameters": {
                    "inputSchema": {
                        "type": "object",
                        "properties": {"amount": {"type": "number"}, "customer": {"type": "string"}},
                    }
                },
            },
            {
                "id": "fields",
                "type": "ops.data.set",
                "typeVersion": 1,
                "name": "Fields",
                "parameters": {"values": {"amount": "$.input.amount", "contact": "$.input.customer"}},
            },
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {"outcome": "ok"}},
        ],
        "connections": [
            {"from": {"node": "start", "port": "payload"}, "to": {"node": "fields", "port": "in"}},
            {"from": {"node": "fields", "port": "out"}, "to": {"node": "done", "port": "in"}},
        ],
    }


def fields(body: dict[str, Any], step: str) -> dict[str, dict[str, Any]]:
    found = next((s for s in body.get("steps") or [] if s["id"] == step), {"fields": []})
    return {f["name"]: f for f in found["fields"]}


with ExitStack() as stack:
    api = stack.enter_context(agents())
    path = f"/v1/workflows/definitions/{WF}"
    saved = api.post("/v1/workflows/definitions", json={"definition": definition()}, headers=TEAM)
    live = api.post(f"{path}/publish-requests", json={"note": "first"}, headers=TEAM)
    before = data(api.get(f"{path}/sample", params={"step": "done"}, headers=TEAM)) or {}
    check(
        "1 before any run the sample lists the earlier steps' fields with no run and no values",
        saved.status_code == 201
        and live.status_code == 201
        and before.get("run") is None
        and set(fields(before, "fields")) >= {"amount", "contact"}
        and fields(before, "start")["amount"]["path"] == "$.input.amount",
        {"saved": saved.status_code, "live": live.status_code, "before": before},
    )

    stack.enter_context(engine_worker("uc512"))
    started = api.post(
        "/v1/runs",
        json={"workflowId": WF, "input": {"amount": 42, "customer": "alex.moreau@harborpine.example"}},
        headers=TEAM,
    )
    run_id = (data(started) or {}).get("runId")
    ended = until(lambda: (r := data(api.get(f"/v1/runs/{run_id}", headers=TEAM))) and r["status"] == "succeeded" and r)
    after = data(api.get(f"{path}/sample", params={"step": "done"}, headers=TEAM)) or {}
    got = fields(after, "fields")
    check(
        "2 after a run each field shows the run's value, the customer's email masked",
        bool(ended)
        and (after.get("run") or {}).get("id") == run_id
        and got.get("amount", {}).get("sample") == "42"
        and "alex.moreau" not in str(got.get("contact", {}).get("sample"))
        and got.get("contact", {}).get("sample") is not None,
        {"started": started.text[:300], "ended": ended, "run": after.get("run"), "fields": got},
    )

    view = data(api.get(path, headers=TEAM)) or {}
    copy = definition()
    copy["nodes"].append(
        {"id": "note", "type": "ops.data.set", "typeVersion": 1, "name": "Note", "parameters": {"values": {"why": "x"}}}
    )
    copy["connections"] = [
        {"from": {"node": "start", "port": "payload"}, "to": {"node": "fields", "port": "in"}},
        {"from": {"node": "fields", "port": "out"}, "to": {"node": "note", "port": "in"}},
        {"from": {"node": "note", "port": "out"}, "to": {"node": "done", "port": "in"}},
    ]
    base = view.get("saveBase") or {}
    put = api.put(
        f"{path}/working-copy",
        json={"definition": copy, "baseVersion": base.get("version"), "baseDigest": base.get("digest")},
        headers=TEAM,
    )
    added = data(api.get(f"{path}/sample", params={"step": "done"}, headers=TEAM)) or {}
    unsaved = data(api.get(f"{path}/sample", params={"step": "drawn_only"}, headers=TEAM)) or {}
    check(
        "3 a step added to the working copy lists its fields at once; a step the copy lacks is not saved yet",
        put.status_code == 200
        and "why" in fields(added, "note")
        and unsaved.get("saved") is False
        and unsaved.get("steps") == [],
        {"put": put.status_code, "steps": [s["id"] for s in added.get("steps") or []], "unsaved": unsaved},
    )

finish()
