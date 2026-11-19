"""uc-757, cli layer: docs/usecases/agents-service/a-builder-writes-a-skill-with.md, step 9. A developer runs
`opsai skills apply` and `opsai skills publish` on a file with steps, `opsai agents apply` on a file with a brief, then
`opsai agents publish-check`, `add-reference` and `publish`. Platform sign-in (lib/main_chains.py bank_stack); no
model is called."""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path
from typing import Any

from apps_walk import ops_cli
from brief_steps import brief, confirm_skill, freeze_skill
from main_chains import bank_stack, publish_bank_module
from usecase_harness import check, finish

RUN = int(time.time())
FILES = Path(tempfile.mkdtemp(prefix="uc757-cli-"))


def written(name: str, body: dict[str, Any]) -> str:
    """A definition file as a developer keeps it; `opsai` reads JSON and YAML alike."""
    path = FILES / f"{name}.json"
    path.write_text(json.dumps(body))
    return str(path)


def answer(result: tuple[int, Any]) -> dict[str, Any]:
    code, out = result
    if code != 0 or not isinstance(out, dict):
        raise SystemExit(f"FAIL opsai: exit {code} {str(out)[:400]}")
    return out


with bank_stack() as s:
    _, read, write = publish_bank_module(
        s.gw, RUN, approval=True, team=s.who["builder"], security=s.who["security"]
    )
    time.sleep(31)  # agents-service keeps each tenant's tool list for 30 seconds

    confirm = answer(ops_cli("builder", "skills", "apply", written("confirm", confirm_skill(RUN, "cli"))))
    answer(ops_cli("builder", "skills", "publish", str(confirm["id"]), "--note", "use case"))
    freeze_file = written("freeze", freeze_skill(RUN, "cli", read, write, str(confirm["id"])))
    freeze = answer(ops_cli("builder", "skills", "apply", freeze_file))
    live_skill = answer(ops_cli("builder", "skills", "publish", str(freeze["id"]), "--note", "use case"))

    # A write step with no rule check is refused, and the command says which rule it broke.
    body = freeze_skill(RUN, "cli", read, write, str(confirm["id"]))
    bare = {**body, "name": f"Bare freeze cli {RUN}", "steps": [*body["steps"][:2], {"do": "Freeze it.", "use": body["steps"][2]["use"]}]}
    code, said = ops_cli("builder", "skills", "apply", written("bare", bare))
    check("9 opsai is refused a write step with no rule check", code != 0 and "write_needs_rule" in json.dumps(said, default=str), (code, said))

    name = f"Freeze desk cli {RUN}"
    agent_file = written("agent", {"name": name, "role": "Freezes accounts", "brief": brief(read)})
    agent = answer(ops_cli("builder", "agents", "apply", agent_file))
    aid = str(agent["id"])
    before = answer(ops_cli("builder", "agents", "publish-check", aid))
    answer(ops_cli("builder", "agents", "add-reference", aid, "tool", read))
    answer(ops_cli("builder", "agents", "add-reference", aid, "skill", str(freeze["id"])))
    after = answer(ops_cli("builder", "agents", "publish-check", aid))
    asked = answer(ops_cli("builder", "agents", "publish", aid, "--note", "use case"))
    live = answer(ops_cli("builder", "agents", "export", aid))
    check(
        "9 opsai applies and publishes a skill with steps and an agent with a brief, after adding what it mentions",
        live_skill.get("publishedVersion") == 1
        and len(live_skill["content"]["steps"]) == 3
        and agent.get("promptMode") == "brief"
        and [p["id"] for p in before["problems"]] == [f"tool:{read}"]
        and after == {"canRequest": True, "problems": []}
        # A brief's never rules are reviewed by a second person, so the request waits for one or is live at once.
        and asked.get("status") in ("pending", "approved")
        and live["uses"]["skills"] == 2,
        (live_skill.get("publishedVersion"), agent.get("promptMode"), before, after, asked.get("status"), live.get("uses")),
    )
finish()
