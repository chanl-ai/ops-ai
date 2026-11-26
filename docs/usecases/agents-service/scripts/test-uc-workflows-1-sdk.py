"""uc-workflows-1, sdk layer: docs/usecases/agents-service/a-schedule-starts-a-run-once.md, steps 1 to 4. James, a
builder, schedules a workflow through `OpsAI.workflows.schedule` in sdk/python: a due tick starts one run, the same
key returns it, another key starts another, and a tick due in an hour stays queued. Step 11: the schedule noun
(`OpsAI.workflows.schedules`) previews, saves and shows a rule with the same words and runs as the API, and a rule
under the floor is refused naming its field. Platform sign-in, agents-service with publish reviews kept pending, and a
workflow worker. No model is called."""

from __future__ import annotations

import secrets
import sys
from datetime import UTC, datetime, timedelta
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
PRIYA = "p.shah@harborpine.example"
AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
    "OPS_REGISTRY_AUTO_APPROVE": "false",
}
CONN: dict[str, Any] = {
    "base_url": "http://127.0.0.1",
    "services": {"platform": f"http://127.0.0.1:{PLATFORM_PORT}", "agents": f"http://127.0.0.1:{AGENTS_PORT}"},
}
TAG = secrets.token_hex(3)
WID = f"ucwf1_sdk_{TAG}"
DEFINITION: dict[str, Any] = {
    "schemaVersion": 2,
    "id": WID,
    "name": f"SDK morning report {TAG}",
    "nodes": [
        {"id": "start", "type": "ops.trigger.schedule", "typeVersion": 1, "parameters": {"key": "morning"}},
        {
            "id": "done",
            "type": "ops.flow.end",
            "typeVersion": 1,
            "parameters": {"outcome": "ticked", "output": "$.input.day"},
        },
    ],
    "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
}

with platform(), agents(env=AUTH):
    # A new workspace publishes at once (publishReview "never"): Priya, the team's admin, turns review on for
    # workflows so Maya's decision is what takes the version live. A policy change refreshes every token, so James
    # and Maya sign in after it.
    priya = OpsAI.sign_in(PRIYA, PASSWORD, team="team_ops", **CONN)
    priya.raw.platform.policies_set_policy("publishReview", {"value": {"workflows": "always"}})
    james = OpsAI.sign_in(JAMES, PASSWORD, team="team_ops", **CONN)
    maya = OpsAI.sign_in(MAYA, PASSWORD, team="team_ops", **CONN)
    james.raw.agents.workflows_create_definition({"definition": DEFINITION})
    review = james.raw.agents.workflows_request_definition_publish(WID, {"note": "First release."})
    maya.raw.agents.reviews_decide_publish_request(review["id"], {"decision": "approved", "reason": "Checked."})
    stage = james.raw.agents.workflows_get_definition(WID).get("stage")

    with engine_worker("ucwf1-sdk"):
        first = james.workflows.schedule(WID, input={"day": "monday"}, key=f"morning-{TAG}-1")
        run = james.runs.wait(first["runId"], timeout=90)
        check(
            "1 a due tick starts one run that ends with the tick's day",
            stage == "live"
            and first["created"] is True
            and run.get("status") == "succeeded"
            and run.get("output") == "monday",
            {
                "stage": stage,
                "created": first.get("created"),
                "run": {k: run.get(k) for k in ("status", "output", "error")},
            },
        )

        again = james.workflows.schedule(WID, input={"day": "monday"}, key=f"morning-{TAG}-1")
        check(
            "2 the same key returns the first run and starts no second",
            again["created"] is False and again["runId"] == first["runId"],
            {"again": again.get("runId"), "first": first.get("runId")},
        )

        other = james.workflows.schedule(WID, input={"day": "tuesday"}, key=f"morning-{TAG}-2")
        other_run = james.runs.wait(other["runId"], timeout=90)
        check(
            "3 another key starts another run with its own day",
            other["runId"] != first["runId"]
            and other_run.get("status") == "succeeded"
            and other_run.get("output") == "tuesday",
            {"run": {k: other_run.get(k) for k in ("status", "output")}},
        )

        due = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        later = james.workflows.schedule(WID, input={"day": "wednesday"}, key=f"morning-{TAG}-3", due_at=due)
        held = james.raw.agents.workflows_get_engine_run(later["runId"])
        check(
            "4 a tick due in an hour stays queued while the due ones have finished",
            held.get("status") == "queued",
            {"status": held.get("status")},
        )

    rule = {"every": 15, "unit": "minutes", "start": "07:00", "tz": "Europe/London"}
    previewed = james.workflows.schedules.preview(kind="every", **rule)
    saved = james.workflows.schedules.save(WID, "start", kind="every", **rule)
    shown = james.workflows.schedules.show(WID, "start")
    try:
        james.workflows.schedules.save(WID, "start", kind="every", every=2, unit="minutes")
        refused: Any = None
    except OpsError as e:
        refused = e
    check(
        "11 the schedule noun previews, saves and shows one rule in the API's words, and refuses one under the floor",
        previewed["words"] == saved["words"] == shown["words"] == "Every 15 minutes from 07:00, Europe/London"
        and previewed["nextRuns"] == saved["nextRuns"]
        and shown["rule"] == saved["rule"]
        and refused is not None
        and (refused.details or {}).get("field") == "every",
        {"preview": previewed.get("words"), "saved": saved.get("words"), "refused": str(refused)[:200]},
    )

finish()
