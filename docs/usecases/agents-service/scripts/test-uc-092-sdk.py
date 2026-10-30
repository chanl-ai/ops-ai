"""uc-092, sdk layer: docs/usecases/agents-service/workflow-lifecycle-and-forms.md, steps 11 to 14. James, a builder,
saves a workflow through the Python SDK in sdk/python; a live run of the draft is refused; his own approval of its
publish is refused and Maya's puts it live; a live run ends refunded with its output. Platform sign-in, agents-service
with publish reviews kept pending, and a workflow worker. No model is called."""

from __future__ import annotations

import secrets
import sys
from pathlib import Path
from typing import Any

from usecase_harness import (
    AGENTS_PORT,
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    agents,
    check,
    engine_worker,
    finish,
    platform,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "sdk" / "python" / "src"))
from ops_ai import OpsAI
from ops_ai.errors import OpsError

JAMES, MAYA, PASSWORD = "j.richardson@harborpine.example", "m.okafor@harborpine.example", "northfield-demo"
AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
    "OPS_REGISTRY_AUTO_APPROVE": "false",
}
# Each service on its own port, as the SDK's example does for a local stack without the proxy.
CONN: dict[str, Any] = {
    "base_url": "http://127.0.0.1",
    "services": {"platform": f"http://127.0.0.1:{PLATFORM_PORT}", "agents": f"http://127.0.0.1:{AGENTS_PORT}"},
}
TAG = secrets.token_hex(3)
DEFINITION: dict[str, Any] = {
    "schemaVersion": 2,
    "id": f"uc092_sdk_{TAG}",
    "name": f"SDK refund {TAG}",
    "nodes": [
        {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
        {
            "id": "done",
            "type": "ops.flow.end",
            "typeVersion": 1,
            "parameters": {"outcome": "refunded", "output": "$.input.amount"},
        },
    ],
    "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
}


def refused(call: Any) -> OpsError | None:
    try:
        call()
    except OpsError as e:
        return e
    return None


with platform(), agents(env=AUTH):
    james = OpsAI.sign_in(JAMES, PASSWORD, team="team_ops", **CONN)
    maya = OpsAI.sign_in(MAYA, PASSWORD, team="team_ops", **CONN)
    wf = DEFINITION["id"]

    james.raw.agents.workflows_create_definition({"definition": DEFINITION})
    stage = james.raw.agents.workflows_get_definition(wf).get("stage")
    early = refused(lambda: james.runs.start(wf, input={"amount": 42}, mode="live"))
    check(
        "11 James saves the workflow as a draft and a live run of it is refused (409 not_live)",
        stage == "draft" and early is not None and early.status == 409 and early.code == "not_live",
        {"stage": stage, "refused": early and (early.status, early.code)},
    )

    review = james.raw.agents.workflows_request_definition_publish(wf, {"note": "First release."})
    mine = {"decision": "approved", "reason": "Mine."}
    own = refused(lambda: james.raw.agents.reviews_decide_publish_request(review["id"], mine))
    check(
        "12 James asks for review and his own approval is refused (403)",
        review.get("status") == "pending" and own is not None and own.status == 403,
        {"review": review.get("status"), "own": own and own.status},
    )

    maya.raw.agents.reviews_decide_publish_request(review["id"], {"decision": "approved", "reason": "Checked."})
    stage = james.raw.agents.workflows_get_definition(wf).get("stage")
    check("13 Maya approves and the workflow is live", stage == "live", {"stage": stage})

    with engine_worker("uc092-sdk"):
        started = james.runs.start(wf, input={"amount": 42}, mode="live")
        run = james.runs.wait(started["runId"], timeout=90)
    check(
        "14 James's live run ends succeeded, outcome refunded, with 42 as its output",
        run.get("status") == "succeeded" and run.get("outcome") == "refunded" and run.get("output") == 42,
        {k: run.get(k) for k in ("status", "outcome", "output", "error")},
    )

finish()
