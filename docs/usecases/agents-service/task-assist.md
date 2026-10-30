# A typed task opens with task assist when the team turns it on

Status: current. Id: `uc-263`. Service: `agents-service`. Layers: api, ui. Card: an earlier change; ui layer an earlier change.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Maya opens a task with task assist off and sees no AI help and no suggestion | ui | 1 | 1 |
| S2 | Priya turns task assist on in Policies, and the next task shows its question, summary and the field worth checking, with Reject marked as suggested and nothing chosen | ui | 2-3 | 3 |
| S3 | A suggestion of an action the task's type does not offer is dropped, and the rest of the help still shows | ui | 5 | 5 |
| S4 | The same through the API: help only when the team has it on, after the question and before the evidence | api | 1-5 | 4 |

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
| ui | `agents-service/scripts/test-uc-263-ui.mjs` | `make usecase-test UC=uc-263 LAYER=ui`: Maya reads the tasks, since James asked for them |
