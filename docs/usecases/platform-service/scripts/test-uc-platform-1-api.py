"""uc-platform-1 a team's running work is counted for that team only and blocks its deletion, api layer:
docs/usecases/platform-service/team-usage-guards-team-deletion.md.

platform-service and agents-service as the console runs them. James makes a workflow live in team_ops and starts one
run that no worker takes. agents-service reports it for team_ops and not for Treasury, a new empty team; the delete
check platform-service builds from that report names the workflow and counts the run. No model call is made."""

from __future__ import annotations

import secrets
from contextlib import ExitStack

from usecase_harness import (
    AGENTS_PORT,
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    bearer,
    check,
    data,
    finish,
    platform,
    signed_in,
)
from usecase_harness import (
    agents as agents_stack,
)

# platform-service reads team usage from this run's agents-service, not from a stack the shell may name.
AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}

WANJIRU, JAMES, MAYA, RAVI = (
    "w.kamau@harborpine.example",
    "j.richardson@harborpine.example",
    "m.okafor@harborpine.example",
    "r.menon@harborpine.example",
)
TAG = secrets.token_hex(3)
NAME = f"Month-end close {TAG}"
WID = f"ucp1_{TAG}"
DEFINITION = {
    "schemaVersion": 2,
    "id": WID,
    "name": NAME,
    "nodes": [
        {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
        {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "closed"}},
    ],
    "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
}

with ExitStack() as stack:
    api, _ = stack.enter_context(platform(env={"OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}))
    agents = stack.enter_context(agents_stack(env=AUTH))
    admin = bearer(signed_in(api, WANJIRU))

    # A new team changes what tokens may carry, so the builders sign in after it exists.
    made = api.post("/v1/settings/teams", json={"name": f"Treasury {TAG}", "admin": RAVI}, headers=admin)
    treasury = (data(made) or {}).get("id", "team_missing")
    ravi = bearer(signed_in(api, RAVI), treasury)
    james = bearer(signed_in(api, JAMES), "team_ops")
    maya = bearer(signed_in(api, MAYA), "team_ops")
    before = data(agents.get("/v1/teams/usage", headers=james)) or {}

    saved = agents.post("/v1/workflows/definitions", json={"definition": DEFINITION}, headers=james)
    asked = agents.post(f"/v1/workflows/definitions/{WID}/publish-requests", json={}, headers=james)
    status = (data(asked) or {}).get("status")
    if status != "approved":
        agents.post(
            f"/v1/reviews/publish-requests/{(data(asked) or {}).get('id')}/decision",
            json={"decision": "approved", "reason": "Checked."},
            headers=maya,
        )
    live = (data(agents.get(f"/v1/workflows/definitions/{WID}", headers=james)) or {}).get("stage")
    started = agents.post("/v1/runs", json={"workflowId": WID, "input": {}}, headers=james)
    check(
        "0 James has a live workflow and one run no worker takes",
        saved.status_code == 201 and live == "live" and started.status_code == 202,
        {"saved": saved.status_code, "stage": live, "started": started.status_code, "asked": asked.text[:200]},
    )

    ops = agents.get("/v1/teams/usage", headers=james)
    check(
        "1 agents-service counts team_ops: one more run in progress and the workflow by name",
        ops.status_code == 200
        and data(ops)
        == {"runsInProgress": before["runsInProgress"] + 1, "liveWorkflows": sorted([*before["liveWorkflows"], NAME])},
        f"{ops.status_code} {ops.text[:300]}",
    )
    empty = agents.get("/v1/teams/usage", headers=ravi)
    check(
        "2 Treasury, a new team, is counted as nothing running",
        empty.status_code == 200 and data(empty) == {"runsInProgress": 0, "liveWorkflows": []},
        f"{empty.status_code} {empty.text[:300]}",
    )

    check_ops = api.get("/v1/settings/teams/team_ops/delete-check", headers=admin)
    body = data(check_ops) or {}
    check(
        "3 the delete check for team_ops carries that count and says it cannot be deleted",
        check_ops.status_code == 200
        and (body.get("usageKnown"), body.get("liveWorkflows"), body.get("runsInProgress"), body.get("canDelete"))
        == (True, sorted([*before["liveWorkflows"], NAME]), before["runsInProgress"] + 1, False),
        (
            body.get("usageKnown"),
            len(body.get("liveWorkflows") or []),
            body.get("runsInProgress"),
            body.get("canDelete"),
            len(before["liveWorkflows"]),
            before["runsInProgress"],
            NAME in (body.get("liveWorkflows") or []),
        ),
    )
    gone = api.delete("/v1/settings/teams/team_ops", headers=admin)
    check(
        "4 deleting team_ops is refused until it is archived (409 not_archived)",
        gone.status_code == 409 and gone.json()["error"]["code"] == "not_archived",
        gone.text[:300],
    )

    archived = api.post(f"/v1/settings/teams/{treasury}/archive", headers=admin)
    check_empty = api.get(f"/v1/settings/teams/{treasury}/delete-check", headers=admin)
    other = data(check_empty) or {}
    check(
        "5 Treasury archived has nothing running but still waits out its days before it can go",
        archived.status_code == 200
        and (other.get("status"), other.get("usageKnown"), other.get("liveWorkflows"), other.get("runsInProgress"))
        == ("archived", True, [], 0)
        and isinstance(other.get("daysLeft"), int)
        and other["daysLeft"] > 0
        and other.get("canDelete") is False,
        check_empty.text[:300],
    )

    refused = api.get("/v1/settings/teams/team_ops/delete-check", headers=james)
    check(
        "6 James, a builder, cannot read the delete check (403)",
        refused.status_code == 403,
        f"{refused.status_code} {refused.text[:200]}",
    )
    denied = api.delete(f"/v1/settings/teams/{treasury}", headers=james)
    check(
        "7 nor can he delete a team (403)",
        denied.status_code == 403,
        f"{denied.status_code} {denied.text[:200]}",
    )

    agents.post(f"/v1/workflows/definitions/{WID}/archive", headers=james)

finish()
