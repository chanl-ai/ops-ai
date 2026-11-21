"""uc-751, cli layer: docs/usecases/agents-service/evals-keep-saved-cases-and-runs.md, story S7. A builder runs
`opsai agents eval` as CI does: a saved judged case that fails stops it (exit 1, the blocked step named, a cost above 0),
a passing case lets it through (exit 0), and an agent that does not exist is exit 2. Platform sign-in and agents-service
on the scripted model."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from apps_walk import AUTH, ops_cli
from usecase_harness import agents, as_role, check, data, finish, platform

# The scripted model's alias needs a price, or every run costs 0 and unpriced.
PRICED = {"OPS_PRICES": json.dumps({"default": {"input": "1000", "output": "3000"}})}
FAILING = {
    "cases": [
        {
            "name": "Never says it",
            "input": "Hello",
            "checks": [
                {"type": "reply_contains", "text": "zzq-never-said-zzq"},
                {"type": "judge", "rubric": "Greets the customer politely"},
            ],
        }
    ]
}
PASSING = {"cases": [{"name": "Replies with words", "input": "Hello", "checks": [{"type": "reply_contains", "text": "could not find"}]}]}


def main() -> None:
    folder = Path(tempfile.mkdtemp(prefix="uc751-cli-"))
    with platform() as (accounts, _), agents(env={**AUTH, **PRICED}) as api:
        builder = as_role(accounts, "builder")
        made = data(api.post("/v1/agents", json={"name": "Fee desk", "role": "Answers questions about fees"}, headers=builder))
        aid = made["id"]
        for name, body in (("failing", FAILING), ("passing", PASSING)):
            (folder / f"{name}.json").write_text(json.dumps(body))

        api.put(f"/v1/agents/{aid}/eval-cases", json=FAILING, headers=builder)
        code, run = ops_cli("builder", "agents", "eval", aid)
        blocked = run if isinstance(run, dict) else {}
        steps = (blocked.get("gate") or {}).get("steps", [])
        check(
            f"33 `opsai agents eval` on a failing judged case exits {code} (1: blocked), names the Pass rate step and costs above 0",
            code == 1 and (blocked.get("gate") or {}).get("blocked") is True
            and any(s["step"] == "pass_rate" and s["result"] == "fail" for s in steps)
            and blocked.get("costUsd", 0) > 0,
            {"exit": code, "reply": str(run)[:300]},
        )
        kept = data(api.get(f"/v1/agents/{aid}/eval-runs", headers=builder))["data"]
        check("34 the run the command started is stored with trigger cli", [r["trigger"] for r in kept] == ["cli"], kept)

        api.put(f"/v1/agents/{aid}/eval-cases", json=PASSING, headers=builder)
        code, run = ops_cli("builder", "agents", "eval", aid)
        gate: Any = (run or {}).get("gate") if isinstance(run, dict) else None
        check(f"35 once the case passes the command exits {code} (0: open)", code == 0 and bool(gate) and gate["blocked"] is False, {"exit": code})

        code, scored = ops_cli("builder", "agents", "eval", aid, "--cases", str(folder / "failing.json"))
        after = data(api.get(f"/v1/agents/{aid}/eval-runs", headers=builder))["data"]
        check(
            f"36 with --cases a failing file exits {code} (1) and keeps no run (still {len(after)} kept)",
            code == 1 and len(after) == 2,
            {"exit": code, "scored": str(scored)[:200]},
        )

        code, _ = ops_cli("builder", "agents", "eval", "ag_does_not_exist")
        check(f"37 an agent that does not exist exits {code} (2: could not run)", code == 2, code)
    finish()


if __name__ == "__main__":
    main()
