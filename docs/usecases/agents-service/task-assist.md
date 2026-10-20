# A typed task opens with task assist when the team turns it on

Status: current. Id: `uc-263`. Service: `agents-service`. Layers: api. Card: c-302.

When a typed task's step pauses in a team that turned task assist on, one model call over what the task shows writes
the question in plain words, a summary, the doubtful fields and a suggested action with its reason. The task shows it
as an `assist` region marked AI, after the question. The person still decides; a suggestion of an action the type does
not offer is dropped. With task assist off (the default) no call is made.

## Preconditions

| Needs | How |
|---|---|
| platform-service, models-service on the fake OpenAI, the agents service and a worker | `scripts/ai_steps_stack.py` |
| The fake model's answers | `services/agents-service/tests/fixtures/ai-steps-fake-openai/script.json` (UC263 markers) |
| Priya Shah, admin of team_ops | the platform dev seed |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Post a generic_decision task with task assist off | The task opens with no assist region |
| 2 | Priya turns task assist on | 200 |
| 3 | Post the same task | An assist with the question, summary, doubtful fields and the suggestion reject, marked AI |
| 4 | — | The regions read header, assist, facts |
| 5 | Post a task the model suggests "escalate" for | The assist shows with no suggestion |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-263-api.py` | `ISOLATED=1 make usecase-test UC=uc-263 LAYER=api` |
