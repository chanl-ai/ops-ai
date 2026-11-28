"""uc-512, sdk layer: docs/usecases/agents-service/step-sheet-plain-words.md, steps 4 and 5. James reads what a step
receives through the Python SDK after one run; Ravi, a viewer, reads it too; Lena, who only chats, is refused.
Platform sign-in, agents-service and a workflow worker. No model is called."""

from __future__ import annotations

import secrets
import sys
import time
from pathlib import Path
from typing import Any

from usecase_harness import AGENTS_PORT, PLATFORM_INTERNAL_PORT, PLATFORM_PORT, agents, check, engine_worker, finish, platform

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "sdk" / "python" / "src"))

from ops_ai import OpsAI
from ops_ai.errors import OpsError

JAMES, RAVI, LENA, PASSWORD = (
    "j.richardson@harborpine.example",
    "r.menon@harborpine.example",
    "l.brandt@harborpine.example",
    "northfield-demo",
)
AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
CONN: dict[str, Any] = {
    "base_url": "http://127.0.0.1",
    "services": {"platform": f"http://127.0.0.1:{PLATFORM_PORT}", "agents": f"http://127.0.0.1:{AGENTS_PORT}"},
}
TAG = secrets.token_hex(3)
WF = f"uc512_sdk_{TAG}"
DEFINITION: dict[str, Any] = {
    "schemaVersion": 2,
    "id": WF,
    "name": f"Claim intake {TAG}",
    "nodes": [
        {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "name": "Claim filed", "parameters": {}},
        {
            "id": "fields",
            "type": "ops.data.set",
            "typeVersion": 1,
            "name": "Claim",
            "parameters": {"values": {"policy": "$.input.policy"}},
        },
        {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {"outcome": "ok"}},
    ],
    "connections": [
        {"from": {"node": "start", "port": "payload"}, "to": {"node": "fields", "port": "in"}},
        {"from": {"node": "fields", "port": "out"}, "to": {"node": "done", "port": "in"}},
    ],
}


def sample(client: OpsAI) -> dict[str, Any]:
    got = client.raw.agents.workflows_definition_sample(WF, step="done")
    return got if isinstance(got, dict) else got.model_dump(by_alias=True)


with platform(), agents(env=AUTH), engine_worker("uc512sdk", AUTH):
    james = OpsAI.sign_in(JAMES, PASSWORD, team="team_ops", **CONN)
    james.raw.agents.workflows_create_definition({"definition": DEFINITION})
    james.raw.agents.workflows_request_definition_publish(WF, {"note": "First."})
    run = james.runs.start(WF, input={"policy": "HP-2291"}, mode="live")
    run_id = run["runId"] if isinstance(run, dict) else run.run_id
    body: dict[str, Any] = {}
    for _ in range(60):
        body = sample(james)
        if body.get("run"):
            break
        time.sleep(1)
    claim = next((s for s in body.get("steps") or [] if s["id"] == "fields"), {"fields": []})
    policy = next((f for f in claim["fields"] if f["name"] == "policy"), {})
    check(
        "4 James reads through the SDK what Done receives: the Claim step's policy with the run's value",
        (body.get("run") or {}).get("id") == run_id and policy.get("sample") == "HP-2291",
        {"run": body.get("run"), "claim": claim},
    )

    ravi = OpsAI.sign_in(RAVI, PASSWORD, team="team_ops", **CONN)
    lena = OpsAI.sign_in(LENA, PASSWORD, team="team_ops", **CONN)
    viewed = sample(ravi)
    try:
        sample(lena)
        refused: int | None = None
    except OpsError as e:
        refused = e.status
    check(
        "5 a viewer reads the sample and a member without the workflows view cell is refused (403)",
        bool(viewed.get("steps")) and refused == 403,
        {"viewer": bool(viewed.get("steps")), "chat_only": refused},
    )

finish()
