"""uc-761, sdk layer: docs/usecases/console/workflow-drafts-and-versions.md, steps 13 to 16. A developer drives a
workflow's working copy through the Python SDK: saves it without making a version, is refused when another builder's
copy is newer, reads what changed and what would publish, and publishes it in one call. Platform sign-in and
agents-service. No model is called."""

from __future__ import annotations

import copy
import secrets
import sys
from pathlib import Path
from typing import Any

from usecase_harness import AGENTS_PORT, PLATFORM_INTERNAL_PORT, PLATFORM_PORT, agents, check, finish, platform

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "sdk" / "python" / "src"))

from ops_ai import OpsAI
from ops_ai.errors import OpsError

JAMES, PRIYA, PASSWORD = "j.richardson@harborpine.example", "p.shah@harborpine.example", "northfield-demo"
AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
CONN: dict[str, Any] = {
    "base_url": "http://127.0.0.1",
    "services": {"platform": f"http://127.0.0.1:{PLATFORM_PORT}", "agents": f"http://127.0.0.1:{AGENTS_PORT}"},
}
WF = f"uc761_sdk_{secrets.token_hex(3)}"
DEFINITION: dict[str, Any] = {
    "schemaVersion": 2,
    "id": WF,
    "name": "Claim intake",
    "nodes": [
        {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "name": "Claim filed", "parameters": {}},
        {"id": "fields", "type": "ops.data.set", "typeVersion": 1, "name": "Claim", "parameters": {"values": {"policy": "$.input.policy"}}},
        {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {"outcome": "ok"}},
    ],
    "connections": [
        {"from": {"node": "start", "port": "payload"}, "to": {"node": "fields", "port": "in"}},
        {"from": {"node": "fields", "port": "out"}, "to": {"node": "done", "port": "in"}},
    ],
}


def versions(client: OpsAI) -> int:
    return len(client.raw.agents.workflows_get_definition(WF)["versions"])


with platform(), agents(env=AUTH):
    james = OpsAI.sign_in(JAMES, PASSWORD, team="team_ops", **CONN)
    priya = OpsAI.sign_in(PRIYA, PASSWORD, team="team_ops", **CONN)
    james.raw.agents.workflows_create_definition({"definition": DEFINITION})
    james.raw.agents.workflows_request_definition_publish(WF, {"note": "First."})
    older = james.workflows.get_definition(WF)["saveBase"]

    changed = copy.deepcopy(DEFINITION)
    changed["nodes"][1]["parameters"]["values"] = {"policy": "$.input.policy", "claimant": "$.input.name"}
    saved = james.workflows.save_working_copy(WF, changed)
    check(
        "13 saving the working copy through the SDK makes no version and returns its checks",
        versions(james) == 1 and saved["workingCopy"]["checks"] == [],
        {"versions": versions(james), "checks": saved["workingCopy"]["checks"]},
    )

    refused_code: str | None = None
    try:
        priya.workflows.save_working_copy(WF, DEFINITION, base=older)
    except OpsError as e:
        refused_code = e.code
    check("14 another builder saving on the older copy is refused as stale (409 stale_base)", refused_code == "stale_base", refused_code)

    diff = james.workflows.diff(WF)
    preview = james.workflows.publish_preview(WF)
    check(
        "15 the diff names the changed step and the preview lists no blocker",
        [s["id"] for s in diff["changed"]] == ["fields"] and preview["blockers"] == [],
        {"diff": diff, "blockers": preview["blockers"]},
    )

    james.workflows.publish(WF, note="Second.", working_copy=True)
    check("16 publishing the working copy in one call makes version 2", versions(james) == 2, versions(james))

finish()
