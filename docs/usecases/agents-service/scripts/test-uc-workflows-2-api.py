"""uc-workflows-2 a builder reads why a test run failed, api layer:
docs/usecases/agents-service/a-builder-reads-why-a-test-run-failed.md, steps 0 to 4.

A builder saves a workflow whose first step reads the customer's email and leads, when there is none, to an End
marked as a failure, and test-runs it on a real worker with a request that names no customer. GET /v1/runs/{id} returns the failure in the one error model: its kind, code and
whether a retry helps, the step that failed, a sentence an end user may read, and the End in `details`. No tool or
model is called."""

from __future__ import annotations

import secrets
from typing import Any

from failed_run_walk import DETAILS, END_NAME, EXPECTED, INPUT, STEP, STEP_NAME, USER_MESSAGE, definition, leaks
from usecase_harness import TEAM, agents, check, data, engine_worker, finish, until

WID = f"ucwf2_api_{secrets.token_hex(3)}"

with agents() as api, engine_worker("ucwf2-api"):
    saved = api.post("/v1/workflows/definitions", json={"definition": definition(WID)}, headers=TEAM)
    check("0 the workflow saves as a draft", saved.status_code == 201, f"{saved.status_code} {saved.text[-300:]}")

    started = api.post("/v1/runs", json={"workflowId": WID, "mode": "test", "input": INPUT}, headers=TEAM)
    run_id = str((data(started) or {}).get("runId"))

    def ended() -> dict[str, Any] | None:
        run = data(api.get(f"/v1/runs/{run_id}", headers=TEAM)) or {}
        return run if run.get("status") in ("succeeded", "failed") else None

    run: dict[str, Any] = until(ended, timeout=60) or {}
    failure: dict[str, Any] = run.get("failure") or {}
    check(
        "1 the test run ends failed, and its error names the step and the End in plain words",
        run.get("status") == "failed" and STEP_NAME in str(run.get("error")) and END_NAME in str(run.get("error")),
        {"http": started.status_code, "status": run.get("status"), "error": run.get("error")},
    )
    check(
        "2 the failure says its kind, its code, whether a retry helps, and which step failed",
        {k: failure.get(k) for k in EXPECTED} == EXPECTED
        and (failure.get("nodeId"), failure.get("nodeName")) == (STEP, STEP_NAME),
        failure,
    )
    said = str(failure.get("userMessage") or "")
    check(
        "3 the sentence for an end user is the code's own, with no step id, code or exception text",
        said == USER_MESSAGE and not leaks(said),
        {"userMessage": said, "leaks": leaks(said)},
    )
    check("4 the failure's details name the End the run stopped at", failure.get("details") == DETAILS, failure)

finish()
