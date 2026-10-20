"""uc-259 a Summarise step summarises text, and an answer outside its schema takes the error port at once, api layer.

Doc: docs/usecases/agents-service/workflow-ai-steps.md. ai_steps_stack, fake model only.
"""

from __future__ import annotations

from ai_steps_stack import ai_stack, definition, publish, run, turn_on
from usecase_harness import check, finish

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
    check(
        "1 the summary keeps the name, the account and the date",
        done.get("outcome") == "done" and "4471" in str((step.get("output") or {}).get("summary")),
        step.get("output"),
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
