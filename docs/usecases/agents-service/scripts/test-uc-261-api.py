"""uc-261 a Draft step writes a reply and sends nothing, api layer.

Doc: docs/usecases/agents-service/workflow-ai-steps.md. ai_steps_stack, fake model only. The step holds no tool, so
the run's steps are the draft and its end: nothing else ran.
"""

from __future__ import annotations

from ai_steps_stack import ai_stack, definition, publish, run, turn_on
from usecase_harness import check, finish

STEP = {
    "id": "reply",
    "type": "ops.ai.draft",
    "typeVersion": 1,
    "parameters": {
        "text": "$.input.body",
        "instructions": "Reply to the customer; confirm what we will do and by when.",
    },
}

with ai_stack("uc261") as (api, people):
    turn_on(people)
    publish(
        api,
        definition(
            "uc261_reply",
            [STEP],
            [("start", "payload", "reply"), ("reply", "ok", "end_drafted"), ("reply", "error", "end_failed")],
        ),
    )
    done = run(api, "uc261_reply", "UC261-REPLY Please close my account 4471 by the end of November. Priya")
    out = (done["byNode"].get("reply") or {}).get("output") or {}
    check(
        "1 the draft has a subject and a body that says what happens and when",
        done.get("outcome") == "drafted" and out.get("subject") and "30 November" in str(out.get("body")),
        out,
    )
    ran = sorted(done["byNode"])
    check("2 nothing ran but the draft and its end: no send", ran == ["end_drafted", "reply", "start"], ran)

finish()
