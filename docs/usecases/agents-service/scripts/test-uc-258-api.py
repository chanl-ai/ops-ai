"""uc-258 a Classify step routes a message by meaning, api layer.

Doc: docs/usecases/agents-service/workflow-ai-steps.md. ai_steps_stack: platform-service for the aiSteps setting,
models-service on the fake OpenAI (fixtures/ai-steps), the agents service and a worker. No real model is called.
"""

from __future__ import annotations

from ai_steps_stack import OPS, ai_stack, definition, publish, run, save, turn_on
from usecase_harness import check, data, finish

CATEGORIES = [
    {"name": "fraud", "description": "The customer reports a payment they did not make"},
    {"name": "billing", "description": "A question about fees or a statement"},
]
STEP = {
    "id": "sort",
    "type": "ops.ai.classify",
    "typeVersion": 1,
    "parameters": {"text": "$.input.body", "categories": CATEGORIES, "minConfidence": 0.6},
}
WIRES = [
    ("start", "payload", "sort"),
    ("sort", "fraud", "end_fraud"),
    ("sort", "billing", "end_billing"),
    ("sort", "otherwise", "end_person"),
    ("sort", "error", "end_failed"),
]

with ai_stack("uc258") as (api, people):
    d = definition("uc258_triage", [STEP], WIRES)
    types = {t["id"]: t for t in data(api.get("/v1/workflows/node-types", headers=OPS))}
    refused = save(api, d)
    check(
        "1 with AI steps off, Classify is listed unavailable with the reason and the workflow is not saved",
        bool(types["ops.ai.classify"]["unavailable"]) and refused.status_code == 422 and "ai_steps_off" in refused.text,
        {"unavailable": types["ops.ai.classify"]["unavailable"], "save": refused.text[:200]},
    )

    on = turn_on(people)
    check("2 the team's admin turns AI steps on (200)", on.status_code == 200, on.text[:200])
    types = {t["id"]: t for t in data(api.get("/v1/workflows/node-types", headers=OPS))}
    publish(api, d)
    check(
        "3 Classify is available and the workflow saves and publishes", types["ops.ai.classify"]["unavailable"] is None
    )

    fraud = run(api, "uc258_triage", "UC258-FRAUD I never paid Acme 900 dollars on my card")
    step = fraud["byNode"].get("sort") or {}
    check(
        "4 a confident answer leaves by its category with the category, confidence and reason",
        fraud.get("outcome") == "fraud" and (step.get("output") or {}).get("category") == "fraud",
        {"outcome": fraud.get("outcome"), "status": fraud.get("status"), "step": step, "error": fraud.get("error")},
    )
    unsure = run(api, "uc258_triage", "UC258-UNSURE Why is there a charge on my statement?")
    check(
        "5 an answer below the floor leaves by otherwise for a person",
        unsure.get("outcome") == "person",
        {"outcome": unsure.get("outcome"), "step": unsure["byNode"].get("sort")},
    )

    stale = definition("uc258_stale", [STEP], [*WIRES, ("sort", "chargeback", "end_chargeback")])
    res = save(api, stale)
    check(
        "6 a wire from a category the step does not have is refused",
        res.status_code == 422 and "definition_checks" in res.text,
        res.text[:200],
    )

finish()
