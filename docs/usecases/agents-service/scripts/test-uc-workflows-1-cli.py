"""uc-workflows-1, cli layer: docs/usecases/agents-service/a-schedule-starts-a-run-once.md, step 12. A builder sets a
workflow's schedule with `opsai workflows schedule` as a script would: preview prints the server's words and next runs,
save applies it and prints the same words, show reads it back, a rule under the floor exits non-zero naming the field,
and clear removes it. Platform sign-in and agents-service; no worker, no model."""

from __future__ import annotations

import json
import secrets
import tempfile
from pathlib import Path

from apps_walk import AUTH, ops_cli
from usecase_harness import agents, as_role, check, data, engine_worker, finish, platform, until

WID = f"ucwf1_cli_{secrets.token_hex(3)}"
DEFINITION = {
    "schemaVersion": 2,
    "id": WID,
    "name": f"CLI morning report {WID[-6:]}",
    "nodes": [
        {"id": "start", "type": "ops.trigger.schedule", "typeVersion": 1, "parameters": {}},
        {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "ticked"}},
    ],
    "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
}
RULE = ["--kind", "every", "--set", "every=15", "--set", "unit=minutes", "--set", "start=07:00"]
RULE += ["--set", "tz=Europe/London"]
WORDS = "Every 15 minutes from 07:00, Europe/London"


def main() -> None:
    with platform() as (plat, _), agents(env=AUTH), engine_worker("ucwf1cli", AUTH):
        source = Path(tempfile.mkdtemp(prefix="ucwf1-cli-")) / "workflow.yaml"
        source.write_text(json.dumps(DEFINITION))
        applied, said = ops_cli("builder", "workflows", "apply", str(source), options_first=True)
        check("set-up: `opsai workflows apply` stores the draft", applied == 0, (applied, said))

        sched = ("workflows", "schedule")
        p_code, previewed = ops_cli("builder", *sched, "preview", *RULE, options_first=True)
        s_code, saved = ops_cli("builder", *sched, "save", WID, "--step", "start", *RULE, options_first=True)
        g_code, shown = ops_cli("builder", *sched, "show", WID, "--step", "start", options_first=True)
        ok = (p_code, s_code, g_code) == (0, 0, 0) and all(isinstance(x, dict) for x in (previewed, saved, shown))
        check(
            "12 preview, save and show print the server's words and the same next runs",
            ok
            and previewed["words"] == saved["words"] == shown["words"] == WORDS  # type: ignore[index]
            and previewed["nextRuns"] == saved["nextRuns"],  # type: ignore[index]
            {"codes": (p_code, s_code, g_code), "preview": previewed, "saved": saved},
        )

        floor_args = ("--kind", "every", "--set", "every=2", "--set", "unit=minutes")
        f_code, refused = ops_cli("builder", *sched, "save", WID, "--step", "start", *floor_args, options_first=True)
        check(
            "12 a rule under the floor exits non-zero and says why",
            f_code != 0 and "At least" in str(refused),
            {"exit": f_code, "said": str(refused)[:300]},
        )

        u_code, unknown = ops_cli(
            "builder", *sched, "save", WID, "--step", "start", "--kind", "daily", "--set", "at=07:30", options_first=True
        )
        check(
            "12 a field the kind does not have exits non-zero naming it",
            u_code != 0 and "at" in str(unknown) and "time" in str(unknown),
            {"exit": u_code, "said": str(unknown)[:300]},
        )

        hourly = ("--kind", "hourly", "--set", "every=1")
        h_code, _ = ops_cli("builder", *sched, "save", WID, "--step", "start", *hourly, options_first=True)
        check("12 a changed schedule saves", h_code == 0, h_code)

        c_code, _ = ops_cli("builder", *sched, "clear", WID, "--step", "start", options_first=True)
        gone_code, gone = ops_cli("builder", *sched, "show", WID, "--step", "start", options_first=True)
        check(
            "12 clear removes the schedule, and show then exits non-zero",
            c_code == 0 and gone_code != 0,
            {"clear": c_code, "show": gone_code, "said": str(gone)[:200]},
        )

        # The three changes are in the account's audit log, delivered by the worker's relay to platform-service.
        admin = as_role(plat, "admin", "team_ops")

        def audit_lines() -> list[str] | None:
            page = data(plat.get("/v1/audit", params={"pageSize": 100}, headers=admin)) or {}
            mine = [e for e in page.get("data") or [] if str(e.get("targetId")) == WID]
            return [str(e["summary"]) for e in mine] if len(mine) >= 3 else None

        lines = sorted(until(audit_lines, timeout=60) or [])
        check(
            "17 a save, a change and a clear each reach the audit log with the old and new schedule in words",
            lines
            == sorted(
                [
                    f"Set the schedule of CLI morning report {WID[-6:]} to {WORDS}",
                    f"Changed the schedule of CLI morning report {WID[-6:]} from {WORDS} to Every hour",
                    f"Cleared the schedule of CLI morning report {WID[-6:]}; it was Every hour",
                ]
            ),
            lines,
        )
    finish()


if __name__ == "__main__":
    main()
