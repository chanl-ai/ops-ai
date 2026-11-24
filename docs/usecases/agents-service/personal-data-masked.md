# Personal data is masked in an agent's replies, stored messages and workflow step output

Status: current. Id: `uc-265`. Service: `agents-service`. Layers: api, ui.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | James asks an agent about Ann in chat; the reply masks her SSN's last four, email, phone and account and keeps her name | ui | 1 | 1 |
| S2 | After a reload the stored reply is masked the same way | ui | 2 | 2 |
| S3 | He turns Redact personal data off on the agent's page and publishes; asked again, the reply is as the model wrote it | ui | 4 | 4 |
| S4 | The same through the API, with a workflow Agent step's output masked | api | 1-4 | 3 |
| S5 | Values named as personal data by their field (ssnLast4, an account id, a number-typed account number) are masked in a chat tool result | api | 5 | 5 |
| S6 | The same values are masked on a run's page and in its events | api | 6-7 | 6 |

With an agent's redact personal data setting on (the default), what its turns show and return has SSNs and their last
four, card and account numbers, emails and phone numbers masked, and every value under a field named as an SSN,
account, card or tax id, numbers included: the streamed reply, the stored message, the recorded
tool calls and a workflow Agent step's output. The model still reads the real values. Names are not masked.

## Preconditions

| Needs | How |
|---|---|
| platform-service, models-service on the fake OpenAI, the agents service and a worker | `scripts/ai_steps_stack.py` |
| The fake model's answers | `services/agents-service/tests/fixtures/ai-steps-fake-openai/script.json` (UC265 markers) |
| Publish review on for team_ops: a new workspace publishes at once | Priya, `PUT /v1/policies/publishReview` (`publishReviewOn` in `docs/usecases/lib/workflow_ui.mjs` for the ui scripts) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Create and publish an agent; ask it about Ann | The reply streams with the SSN's last four, email, phone and account masked; "Ann Lee" stays |
| 2 | Read the thread | The stored reply is the masked one |
| 3 | Run a workflow whose Agent step summarises Priya | The step's summary is masked and names Priya |
| 5 | Ask the agent for Ann's record (the fake model presents ssnLast4, accountId and a number-typed accountNumber) | The record part streams and is stored with [SSN] and [account] in place of the values; "Ann Lee" stays |
| 6 | Run a workflow whose Agent step returns ssnLast4, accountIds and a number-typed accountNumber | The run's page shows the step's output masked and names Ann Lee |
| 7 | Read the run's events | The step's frames say it started and ended and carry none of the values |
| 4 | Turn redactPii off, publish, Priya approves (a security change waits for review in every mode), ask again | The reply is as the model wrote it |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-265-api.py` | `make usecase-test UC=uc-265 LAYER=api` |
| ui | `agents-service/scripts/test-uc-265-ui.mjs` | `make usecase-test UC=uc-265 LAYER=ui`: chat, a reload, and the agent page's switch |
