"""uc-workflows-2, sdk layer: docs/usecases/agents-service/a-builder-reads-why-a-test-run-failed.md, steps 5 and 6.
James, a builder, saves the workflow and test-runs it through `OpsAI.runs` in sdk/python: `runs.wait(check=True)`
raises RunFailed carrying the failure in the one error model. Platform sign-in, agents-service and a workflow worker.
No tool or model is called."""

from __future__ import annotations

import secrets
import sys
from pathlib import Path
from typing import Any

from failed_run_walk import DETAILS, EXPECTED, INPUT, STEP_NAME, USER_MESSAGE, definition, leaks
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
from ops_ai.errors import RunFailed

JAMES, PASSWORD = "j.richardson@harborpine.example", "northfield-demo"
AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
CONN: dict[str, Any] = {
    "base_url": "http://127.0.0.1",
    "services": {"platform": f"http://127.0.0.1:{PLATFORM_PORT}", "agents": f"http://127.0.0.1:{AGENTS_PORT}"},
}
WID = f"ucwf2_sdk_{secrets.token_hex(3)}"

with platform(), agents(env=AUTH), engine_worker("ucwf2-sdk"):
    james = OpsAI.sign_in(JAMES, PASSWORD, team="team_ops", **CONN)
    james.raw.agents.workflows_create_definition({"definition": definition(WID)})
    started = james.runs.start(WID, input=INPUT, mode="test")
    raised: RunFailed | None = None
    returned: Any = None
    try:
        returned = james.runs.wait(str(started["runId"]), timeout=90, check=True)
    except RunFailed as e:
        raised = e
    read = {k: getattr(raised, k, None) for k in EXPECTED}
    check(
        "5 runs.wait(check=True) raises RunFailed with the kind, the code, whether a retry helps, and the failed step",
        raised is not None and read == EXPECTED and raised.step == STEP_NAME,
        {"raised": str(raised), "read": read, "returned": returned},
    )
    said = raised.user_message if raised else ""
    details = ((raised.run.get("failure") or {}) if raised else {}).get("details")
    check(
        "6 the raised error carries the end user's sentence with nothing leaked, and the run's details name the End",
        said == USER_MESSAGE and not leaks(said) and details == DETAILS,
        {"user_message": said, "leaks": leaks(said), "details": details},
    )

finish()
