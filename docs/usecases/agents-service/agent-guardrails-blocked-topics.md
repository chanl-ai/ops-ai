# An agent refuses a blocked topic before answering, through a guardrail it pins by version

Status: passing. Id: `uc-085`. Service: `agents-service`. Layers: api, ui. Card: c-063 (T006, T007, T008, T012, T013).

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The banker demo stack: models-service on the fake OpenAI with the committed demo rules, tools-service and the fake bank, kb-service | `demo()` in `lib/usecase_harness.py`, on the run's own ports |
| The guardrail `gr_no_investment_advice` (blocks "investment advice") pinned on `ag_advisor` | `services/agents-service/seed/guardrails.json`, loaded at start beside the agents seed |
| The skill `sk_hardship_triage` (always on, no tools) attached to `ag_advisor` | `services/agents-service/seed/skills.json`, loaded the same way |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `GET /v1/agents/ag_advisor`, `GET /v1/guardrails/gr_no_investment_advice` | the guardrail is published at v1; the advisor pins exactly v1 |
| 2 | Ask the advisor "Should my client buy Harbor & Pine shares?" | the reply is the guardrail's message; the done message carries `guardrail {guardrailId, version 1, topic "investment advice", when "before"}`; the thread's only model call is the classification |
| 3 | Ask "What does Priya Natarajan have with us?" | a normal answer from the customer tools; the model calls are a classification, the answering calls, then a classification of the answer |
| 4 | Ask "My client lost her job and cannot make this month's mortgage payment. What can we do?" | Hardship request triage v1 is in the prompt on every turn, so no `load_skill` call is needed; the done message's `skills` names it as "Always on"; the answer follows the skill (the hardship request form) |
| 5 | Stop the fake OpenAI and ask again | an error event with code `guardrail_unavailable`; no answering call recorded |
| 6 | On the agent page, switch "No investment advice" off, save, publish, and ask the shares question again (ui) | the page shows "Off · not checked"; the saved pin has `enabled: false`; the reply is not the guardrail's message and no classification runs; after a reload it still shows Off |

Step 3 asks about a customer rather than the wire fee in the spec: the advisor answers fee questions only with the
policy knowledge base, which the demo wires to `ag_policy`; the customer question is the advisor's own path.

Model calls are read from `model_call_records` by thread: a classification is the response calling `final_result`,
anything else is the answering model.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-085-api.py` | passing |
| ui | `agents-service/scripts/test-uc-085-ui.mjs` | passing |

The ui layer, signed in as James on the demo stack: the blocked question in chat shows the guardrail's message and
the line naming the guardrail that refused it; the agent page shows the pin checked and marked Enforced, with
redaction and when-unsure marked "Not enforced yet"; unchecking the pin and saving sends a draft with no pin. The
hardship question shows "Loaded skill Hardship request triage v1" on the turn, and the agent page lists the skill
from its own request to agents-service (the mock has a skill of the same name). On the Guardrails page a builder
creates "No tax advice", publishes v1, and the agent page offers it to pin.

## Non-vacuous check

With `UC085_UNPINNED=1` the script detaches the skill, unpins the guardrail and publishes the advisor before step 2. Seen on
2026-10-16: step 2 fails with the scripted answer and calls `['answer']`, step 3 with no classification around the
answer, and step 5 with `502 provider_error` in place of `guardrail_unavailable`. Kernel tests
`test_guardrails_kernel.py` fail 3 of 7 with the before-check removed. With the agent page's draft ignoring the
agent's pins, the ui layer's page and unpin checks failed (pinned false, the saved draft still pinning v1). With the
skill detached as well, step 4 fails with no pin and no skill on the turn (seen 2026-10-18). With the console's skills left
on the mock in registry mode, the ui layer stops at the agent-skills check (no request reaches agents-service).
