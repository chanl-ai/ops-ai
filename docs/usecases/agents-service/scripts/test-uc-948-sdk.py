"""uc-948, sdk layer: docs/usecases/agents-service/agent-page-in-one-editor.md, steps 5 and 6. A developer applies an
agent with a seven-field brief through the Python SDK, reads it back equal, and is told in the one blocker shape what a
mentioned workflow lacks. Platform sign-in and agents-service; no model is called."""

from __future__ import annotations

import secrets
import sys
from pathlib import Path
from typing import Any

from usecase_harness import AGENTS_PORT, PLATFORM_INTERNAL_PORT, PLATFORM_PORT, agents, check, finish, platform

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "sdk" / "python" / "src"))

from ops_ai import OpsAI

AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
CONN: dict[str, Any] = {
    "base_url": "http://127.0.0.1",
    "services": {"platform": f"http://127.0.0.1:{PLATFORM_PORT}", "agents": f"http://127.0.0.1:{AGENTS_PORT}"},
}
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

with platform(), agents(env=AUTH):
    ops = OpsAI.sign_in("j.richardson@harborpine.example", "northfield-demo", team="team_ops", **CONN)
    agent = ops.agents.apply({"name": f"Dispute desk sdk {TAG}", "role": "Answers disputes", "brief": BRIEF})
    read = ops.agents.get(str(agent["id"]))
    same = {k: (read.get("brief") or {}).get(k) for k in BRIEF}
    check(
        "5 an agent applied with a seven-field brief reads back the same through the SDK",
        same == BRIEF and read["promptMode"] == "brief",
        {k: (same.get(k), BRIEF[k]) for k in BRIEF if same.get(k) != BRIEF[k]},
    )
    ghost = ops.agents.apply(
        {"name": f"Workflow desk sdk {TAG}", "role": "Starts a workflow", "brief": {**BRIEF, "howToAnswer": "Start it with @workflow:ghost_dispute."}}
    )
    got = ops.agents.publish_check(str(ghost["id"]))
    check(
        "6 a mentioned workflow the team lacks blocks the publish, in the one blocker shape",
        got["canRequest"] is False and got["blockers"] and {"code", "message"} <= set(got["blockers"][0]),
        got,
    )

finish()
