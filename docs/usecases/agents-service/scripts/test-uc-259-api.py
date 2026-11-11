"""uc-259 a Summarise step summarises text, and an answer outside its schema takes the error port at once, api layer.

Doc: docs/usecases/agents-service/workflow-ai-steps.md. ai_steps_stack, fake model only.
"""

from __future__ import annotations

from ai_steps_stack import ai_stack, definition, publish, run, turn_on
from usecase_harness import bearer, check, finish, signed_in

STEP = {
    "id": "sum",
    "type": "ops.ai.summarise",
    "typeVersion": 1,
    "parameters": {"text": "$.input.body", "maxWords": 40},
}

with ai_stack("uc259") as (api, people):
    turn_on(people)
    publish(
        api,
        definition(
            "uc259_notes",
            [STEP],
            [("start", "payload", "sum"), ("sum", "ok", "end_done"), ("sum", "error", "end_failed")],
        ),
    )

    done = run(
        api, "uc259_notes", "UC259-NOTE Priya Natarajan called: please close savings account 4471 by 30 November 2026."
    )
    step = done["byNode"].get("sum") or {}
    text = str((step.get("output") or {}).get("summary"))
    check(
        "1 the summary keeps the name and the date, and a run page shows the account number masked",
        done.get("outcome") == "done"
        and "Priya Natarajan" in text
        and "30 November 2026" in text
        and "account ••••" in text
        and "4471" not in text,
        step.get("output"),
    )
    priya = bearer(signed_in(people, "p.shah@harborpine.example"), "team_ops")
    people.put("/v1/policies/aiStepsMaskPersonalData", json={"value": False}, headers=priya)
    real = run(
        api, "uc259_notes", "UC259-NOTE Priya Natarajan called: please close savings account 4471 by 30 November 2026."
    )
    shown = str(((real["byNode"].get("sum") or {}).get("output") or {}).get("summary"))
    check(
        "1b with masking turned off by the team, the same summary shows account 4471",
        real.get("outcome") == "done" and "account 4471" in shown,
        shown,
    )
    broken = run(api, "uc259_notes", "UC259-BROKEN anything")
    bad = broken["byNode"].get("sum") or {}
    check(
        "2 an answer outside the schema leaves by error with schema_error, on its first attempt",
        broken.get("outcome") == "failed"
        and (bad.get("output") or {}).get("code") == "schema_error"
        and len(bad.get("attempts") or []) == 1,
        {"outcome": broken.get("outcome"), "step": bad},
    )

finish()
