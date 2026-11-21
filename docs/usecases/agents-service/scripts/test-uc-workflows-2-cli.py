"""uc-workflows-2, cli layer: docs/usecases/agents-service/a-builder-reads-why-a-test-run-failed.md, steps 7 and 8.
A builder applies the workflow from a file and test-runs it with `opsai runs start --wait`, signed in as their dev
role the way `make api` signs in (`opsai --as`): the command exits with the status for the failure's kind and prints
one line saying why, and `opsai runs show` returns the same failure. Platform sign-in, agents-service and a workflow
worker. No tool or model is called."""

from __future__ import annotations

import json
import secrets
import tempfile
from pathlib import Path
from typing import Any

from apps_walk import AUTH, ops_cli
from failed_run_walk import DETAILS, EXIT, EXPECTED, INPUT, STEP, STEP_NAME, USER_MESSAGE, definition, leaks
from usecase_harness import agents, check, engine_worker, finish, platform

WID = f"ucwf2_cli_{secrets.token_hex(3)}"


def main() -> None:
    with platform(), agents(env=AUTH), engine_worker("ucwf2-cli"):
        # JSON is YAML, so the definition the other layers send is the file a builder applies.
        source = Path(tempfile.mkdtemp(prefix="ucwf2-cli-")) / "workflow.yaml"
        source.write_text(json.dumps(definition(WID)))
        applied_code, applied = ops_cli("builder", "workflows", "apply", str(source), options_first=True)
        check("set-up: `opsai workflows apply` stores the draft", applied_code == 0, (applied_code, applied))

        code, said = ops_cli("builder", "runs", "start", WID, "--input", json.dumps(INPUT), "--wait")
        line = said if isinstance(said, str) else json.dumps(said)
        wanted = (f"{EXPECTED['kind']}/{EXPECTED['code']}", f'at "{STEP_NAME}"', "not retryable")
        check(
            "7 `opsai runs start --wait` exits with the refused status and one line naming the kind, code and step",
            code == EXIT and all(w in line for w in wanted) and "Traceback" not in line,
            {"exit": code, "said": line},
        )

        _, listed = ops_cli("builder", "runs", "list", "--workflow", WID)
        rows: list[dict[str, Any]] = listed if isinstance(listed, list) else []
        shown_code, shown = ops_cli("builder", "runs", "show", str(rows[0]["id"]) if rows else "none")
        failure: dict[str, Any] = (shown.get("failure") or {}) if isinstance(shown, dict) else {}
        message = str(failure.get("userMessage") or "")
        check(
            "8 `opsai runs show` returns the failure: kind, code, retryable, step, the end user's sentence, details",
            shown_code == 0
            and {k: failure.get(k) for k in EXPECTED} == EXPECTED
            and failure.get("nodeId") == STEP
            and message == USER_MESSAGE
            and not leaks(message)
            and failure.get("details") == DETAILS,
            {"exit": shown_code, "runs": len(rows), "failure": failure or shown},
        )
    finish()


if __name__ == "__main__":
    main()
