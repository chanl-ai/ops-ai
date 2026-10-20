"""uc-260 an Extract from text step reads fields from a message, api layer.

Doc: docs/usecases/agents-service/workflow-ai-steps.md. ai_steps_stack, fake model only.
"""

from __future__ import annotations

from ai_steps_stack import ai_stack, definition, publish, run, turn_on
from usecase_harness import check, finish

FIELDS = [
    {"key": "amount", "label": "Amount", "type": "money"},
    {"key": "case_no", "label": "Case number", "type": "text"},
    {"key": "court", "label": "Court", "type": "text"},
]
STEP = {
    "id": "read",
    "type": "ops.ai.extractText",
    "typeVersion": 1,
    "parameters": {"text": "$.input.body", "fields": FIELDS},
}

with ai_stack("uc260") as (api, people):
    turn_on(people)
    publish(
        api,
        definition(
            "uc260_levy_mail",
            [STEP],
            [("start", "payload", "read"), ("read", "ok", "end_done"), ("read", "error", "end_failed")],
        ),
    )
    done = run(api, "uc260_levy_mail", "UC260-LEVY Please process the levy of 3,250.00 on case NS-2026-GN-01187.")
    out = (done["byNode"].get("read") or {}).get("output") or {}
    check(
        "1 each field is read by its key, and one the text does not state is null",
        done.get("outcome") == "done" and out == {"amount": 3250.0, "case_no": "NS-2026-GN-01187", "court": None},
        out,
    )

finish()
