"""uc-262 one workflow classifies, summarises, extracts and drafts on the fake model, api layer.

Doc: docs/usecases/agents-service/workflow-ai-steps.md. ai_steps_stack, fake model only. Each step reads the message
under its own prefix so the fake model's rules tell the four calls apart.
"""

from __future__ import annotations

from ai_steps_stack import ai_stack, definition, publish, run, turn_on
from usecase_harness import check, finish

CATEGORIES = [
    {"name": "fraud", "description": "The customer reports a payment they did not make"},
    {"name": "billing", "description": "A question about fees or a statement"},
]
FIELDS = [{"key": "amount", "type": "money"}, {"key": "merchant"}, {"key": "date", "type": "date"}]
STEPS = [
    {
        "id": "sort",
        "type": "ops.ai.classify",
        "typeVersion": 1,
        "parameters": {"text": "classify {$.input.body}", "categories": CATEGORIES},
    },
    {"id": "gist", "type": "ops.ai.summarise", "typeVersion": 1, "parameters": {"text": "summary {$.input.body}"}},
    {
        "id": "facts",
        "type": "ops.ai.extractText",
        "typeVersion": 1,
        "parameters": {"text": "fields {$.input.body}", "fields": FIELDS},
    },
    {
        "id": "reply",
        "type": "ops.ai.draft",
        "typeVersion": 1,
        "parameters": {"text": "draft {$.input.body}", "instructions": "Tell the customer a dispute is open."},
    },
]
WIRES = [
    ("start", "payload", "sort"),
    ("sort", "fraud", "gist"),
    ("sort", "billing", "end_billing"),
    ("sort", "otherwise", "end_person"),
    ("sort", "error", "end_failed"),
    ("gist", "ok", "facts"),
    ("gist", "error", "end_failed"),
    ("facts", "ok", "reply"),
    ("facts", "error", "end_failed"),
    ("reply", "ok", "end_disputed"),
    ("reply", "error", "end_failed"),
]

with ai_stack("uc262") as (api, people):
    turn_on(people)
    publish(api, definition("uc262_dispute_mail", STEPS, WIRES))
    done = run(api, "uc262_dispute_mail", "UC262-MAIL Hi, I did not pay Acme 900.00 on 14 October. Ann Lee")
    out = {n: (s.get("output") or {}) for n, s in done["byNode"].items()}
    check(
        "1 the message is classified as fraud and the run takes that branch",
        done.get("outcome") == "disputed" and out.get("sort", {}).get("category") == "fraud",
        {"outcome": done.get("outcome"), "sort": out.get("sort")},
    )
    check("2 it is summarised", "900.00" in str(out.get("gist", {}).get("summary")), out.get("gist"))
    check(
        "3 its fields are read",
        out.get("facts") == {"amount": 900.0, "merchant": "Acme", "date": "2026-10-14"},
        out.get("facts"),
    )
    check("4 a reply is drafted", "dispute" in str(out.get("reply", {}).get("body")), out.get("reply"))

finish()
