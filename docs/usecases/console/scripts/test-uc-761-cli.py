"""uc-761, cli layer: docs/usecases/console/workflow-drafts-and-versions.md, steps 17 to 19. A developer runs
`opsai workflows save-copy`, `diff` and `publish --working-copy` as a builder. Platform sign-in and agents-service.
No model is called."""

from __future__ import annotations

import copy
import json
import secrets
import tempfile
from pathlib import Path
from typing import Any

from apps_walk import AUTH, ops_cli
from usecase_harness import agents, check, finish, platform

WF = f"uc761_cli_{secrets.token_hex(3)}"
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


def written(name: str, body: dict[str, Any]) -> str:
    path = Path(tempfile.mkdtemp(prefix="uc761-cli-")) / f"{name}.json"
    path.write_text(json.dumps(body))
    return str(path)


with platform(), agents(env=AUTH):
    code, made = ops_cli("builder", "workflows", "apply", written("first", DEFINITION), options_first=True)
    ops_cli("builder", "workflows", "publish", WF, "--note", "First.", options_first=True)
    changed = copy.deepcopy(DEFINITION)
    changed["nodes"][1]["parameters"]["values"] = {"policy": "$.input.policy", "claimant": "$.input.name"}
    saved_code, saved = ops_cli("builder", "workflows", "save-copy", WF, written("changed", changed), options_first=True)
    diff_code, diff = ops_cli("builder", "workflows", "diff", WF, options_first=True)
    check(
        "17 `opsai workflows save-copy` saves the working copy and `diff` names the changed step",
        code == 0 and saved_code == 0 and diff_code == 0 and [s["id"] for s in diff["changed"]] == ["fields"],
        {"apply": code, "save": (saved_code, saved), "diff": (diff_code, diff)},
    )
    published_code, published = ops_cli("builder", "workflows", "publish", WF, "--note", "Second.", "--working-copy", options_first=True)
    shown_code, shown = ops_cli("builder", "workflows", "export", WF, "--format", "json", options_first=True)
    check(
        "18 `opsai workflows publish --working-copy` makes the next version live with the change",
        published_code == 0 and shown_code == 0 and "claimant" in json.dumps(shown),
        {"publish": (published_code, published), "export": shown_code},
    )

finish()
