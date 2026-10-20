# A workflow uses AI steps without a saved agent

Status: current. Ids: `uc-258` to `uc-262`. Service: `agents-service`. Layers: api. Card: c-298.

Classify, Summarise, Extract from text and Draft are workflow steps that make one model call each, with the step's own
instructions and model alias, no saved agent and no tools. Classify leaves by a category's port, or by `otherwise`
below its confidence floor. A team's AI steps are off until someone who may manage workflow settings turns them on.

## Preconditions

| Needs | How |
|---|---|
| platform-service, models-service on the fake OpenAI, the agents service and a worker | `scripts/ai_steps_stack.py` |
| The fake model's answers | `services/agents-service/tests/fixtures/ai-steps-fake-openai/script.json`, matched by a marker in the text |
| Priya Shah, admin of team_ops | the platform dev seed |

## Steps and expected results

| Id | Step | Expected |
|---|---|---|
| uc-258 | With AI steps off, list step types and save a Classify workflow | Classify unavailable with the reason; the save is 422 `ai_steps_off` |
| uc-258 | Priya turns AI steps on; run a fraud message and an unsure one | fraud leaves by `fraud` with confidence and reason; the unsure one by `otherwise` |
| uc-258 | Save a wire from a category the step does not have | 422 `definition_checks` |
| uc-259 | Summarise a note; summarise text the model answers outside the schema | the summary; the second leaves by `error` with `schema_error` after one call |
| uc-260 | Extract from text with fields of the step's own | each field's value, null for one the text does not state |
| uc-261 | Draft a reply | subject and body; the run sends nothing |
| uc-262 | One workflow: Classify, then Summarise, Extract from text and Draft | each step's output on the run, ending on the category's branch |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-258-api.py` to `test-uc-262-api.py` | `ISOLATED=1 make usecase-test UC=uc-258 LAYER=api` |
