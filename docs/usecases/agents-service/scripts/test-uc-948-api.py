"""uc-948, api layer: docs/usecases/agents-service/agent-page-in-one-editor.md, steps 1 to 4. A builder saves an agent's
brief with every field, reads the prompt it makes (Never last), asks for a publish that waits for a reviewer, takes it
back, sends it again and saves meanwhile without the waiting version changing, and is told in one blocker shape what a
mentioned workflow lacks. The dev caller on the scripted model: a publish waits for a review here."""

from __future__ import annotations

import os
import time
from typing import Any

# A publish goes through a second person, as outside dev, and a requester may take their own request back.
os.environ["OPS_REGISTRY_AUTO_APPROVE"] = "false"
os.environ["OPS_DEV_POLICIES"] = '{"requesterMayDecide": false}'

from usecase_harness import TEAM, agents, check, data, finish, save_agent

RUN = int(time.time())
BRIEF: dict[str, Any] = {
    "purpose": "Answers cardholders about disputes.",
    "goal": "Every dispute ends with a clear next step.",
    "howToAnswer": "Keep answers short and say what you checked.",
    "handOff": ["The cardholder asks for a person", "The charge is over the card limit"],
    "examples": "Cardholder: Can I dispute a charge? You: Yes, tell me the date and the amount.",
    "never": ["Promise a refund before the review"],
    "success": ["The cardholder knows what happens next"],
}


def made(res: Any) -> dict[str, Any]:
    if res.status_code not in (200, 201):
        raise SystemExit(f"FAIL setup: {res.status_code} {res.text[:400]}")
    return data(res)


with agents() as api:
    agent = made(api.post("/v1/agents", json={"name": f"Dispute desk {RUN}", "role": "Answers disputes"}, headers=TEAM))
    aid = str(agent["id"])
    saved = made(save_agent(api, aid, {"brief": BRIEF}, headers=TEAM))
    read = made(api.get(f"/v1/agents/{aid}", headers=TEAM))
    same = {k: (read.get("brief") or {}).get(k) for k in BRIEF}
    check(
        "1 a brief with all seven fields saves and reads back the same",
        same == BRIEF and saved["promptMode"] == "brief",
        {k: (same.get(k), BRIEF[k]) for k in BRIEF if same.get(k) != BRIEF[k]},
    )

    shown = made(api.get(f"/v1/agents/{aid}/prompt", params={"version": read["version"]}, headers=TEAM))
    prompt = str(shown.get("prompt") or shown.get("text") or shown)
    heads = [h for h in ("# Who you are", "# Goal", "# How to answer", "# Hand off", "# Examples", "# Never") if h in prompt]
    check(
        "2 the prompt the brief makes has its bands in order and Never last",
        len(heads) == 6 and [prompt.index(h) for h in heads] == sorted(prompt.index(h) for h in heads) and heads[-1] == "# Never" and prompt.rindex("# ") == prompt.index("# Never"),
        (heads, prompt[-200:], list(shown)[:6]),
    )

    asked = made(api.post(f"/v1/agents/{aid}/publish-requests", json={"version": read["version"], "note": "first"}, headers=TEAM))
    waiting_before = next((v for v in made(api.get(f"/v1/agents/{aid}/versions", headers=TEAM)) if v["version"] == read["version"]), {})
    edited = save_agent(api, aid, {"brief": {**BRIEF, "goal": "A different goal."}}, headers=TEAM)
    after_view = made(api.get(f"/v1/agents/{aid}", headers=TEAM))
    waiting = next((v for v in made(api.get(f"/v1/agents/{aid}/versions", headers=TEAM)) if v["version"] == read["version"]), {})
    withdrawn = api.post(f"/v1/publish-requests/{asked['id']}/withdraw", headers=TEAM)
    again = api.post(f"/v1/agents/{aid}/publish-requests", json={"version": after_view["version"], "note": "again", "follows": asked["id"]}, headers=TEAM)
    check(
        "3 a waiting version names its review, is never edited in place (a save opens the next one), and the request can be taken back and sent again",
        asked["status"] == "pending"
        and edited.status_code == 200
        and after_view["version"] == read["version"] + 1
        and (waiting.get("savedAt"), waiting.get("changes")) == (waiting_before.get("savedAt"), waiting_before.get("changes")) and waiting.get("state") == "in_review"
        and waiting.get("reviewId") == asked["id"]
        and withdrawn.status_code == 200
        and again.status_code == 201,
        (asked["status"], edited.status_code, after_view.get("version"), waiting.get("state"), waiting_before.get("state"), waiting.get("reviewId"), withdrawn.status_code, again.status_code, again.text[:200]),
    )

    mentions = made(api.post("/v1/agents", json={"name": f"Workflow desk {RUN}", "role": "Starts a workflow"}, headers=TEAM))
    made(save_agent(api, mentions["id"], {"brief": {**BRIEF, "howToAnswer": "Start the dispute with @workflow:ghost_dispute."}}, headers=TEAM))
    got = made(api.get(f"/v1/agents/{mentions['id']}/publish-check", params={"version": 1}, headers=TEAM))
    blockers = got.get("blockers") or []
    check(
        "4 a mentioned workflow the team lacks blocks the publish, in the one blocker shape",
        got["canRequest"] is False and blockers and {"code", "message"} <= set(blockers[0]),
        got,
    )

finish()
