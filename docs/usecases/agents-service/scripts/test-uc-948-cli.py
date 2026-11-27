"""uc-948, cli layer: docs/usecases/agents-service/agent-page-in-one-editor.md, steps 7 and 8. A developer applies an
agent file with a seven-field brief with `opsai agents apply`, exports it equal, and `publish-check` names what a
mentioned workflow lacks in the one blocker shape. Platform sign-in and agents-service; no model is called."""

from __future__ import annotations

import json
import secrets
import tempfile
from pathlib import Path
from typing import Any

from apps_walk import AUTH, ops_cli
from usecase_harness import agents, check, finish, platform

TAG = secrets.token_hex(3)
BRIEF: dict[str, Any] = {
    "purpose": "Answers cardholders about disputes.",
    "goal": "Every dispute ends with a clear next step.",
    "howToAnswer": "Keep answers short and say what you checked.",
    "handOff": ["The cardholder asks for a person"],
    "examples": "Cardholder: Can I dispute a charge? You: Yes, tell me the date and the amount.",
    "never": ["Promise a refund before the review"],
    "success": ["The cardholder knows what happens next"],
}


def written(name: str, body: dict[str, Any]) -> str:
    path = Path(tempfile.mkdtemp(prefix="uc948-cli-")) / f"{name}.json"
    path.write_text(json.dumps(body))
    return str(path)


with platform(), agents(env=AUTH):
    code, agent = ops_cli("builder", "agents", "apply", written("desk", {"name": f"Dispute desk cli {TAG}", "role": "Answers disputes", "brief": BRIEF}))
    ex_code, exported = ops_cli("builder", "agents", "export", str(agent["id"]) if isinstance(agent, dict) else "none")
    same = {k: ((exported.get("brief") or {}) if isinstance(exported, dict) else {}).get(k) for k in BRIEF}
    check(
        "7 `opsai agents apply` stores a seven-field brief and `export` returns it equal",
        code == 0 and ex_code == 0 and same == BRIEF,
        {"apply": code, "export": ex_code, "differs": {k: (same.get(k), BRIEF[k]) for k in BRIEF if same.get(k) != BRIEF[k]}},
    )
    g_code, ghost = ops_cli("builder", "agents", "apply", written("ghost", {"name": f"Workflow desk cli {TAG}", "role": "Starts a workflow", "brief": {**BRIEF, "howToAnswer": "Start it with @workflow:ghost_dispute."}}))
    c_code, got = ops_cli("builder", "agents", "publish-check", str(ghost["id"]) if isinstance(ghost, dict) else "none")
    blockers = got.get("blockers") if isinstance(got, dict) else None
    check(
        "8 `opsai agents publish-check` names a mentioned workflow the team lacks in the one blocker shape",
        g_code == 0 and c_code == 0 and isinstance(got, dict) and got.get("canRequest") is False and bool(blockers) and {"code", "message"} <= set(blockers[0]),
        got,
    )

finish()
