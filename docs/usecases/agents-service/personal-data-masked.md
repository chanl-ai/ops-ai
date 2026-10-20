# Personal data is masked in an agent's replies, stored messages and workflow step output

Status: current. Id: `uc-265`. Service: `agents-service`. Layers: api. Card: c-293.

With an agent's redact personal data setting on (the default), what its turns show and return has SSNs and their last
four, card and account numbers, emails and phone numbers masked: the streamed reply, the stored message, the recorded
tool calls and a workflow Agent step's output. The model still reads the real values. Names are not masked.

## Preconditions

| Needs | How |
|---|---|
| platform-service, models-service on the fake OpenAI, the agents service and a worker | `scripts/ai_steps_stack.py` |
| The fake model's answers | `services/agents-service/tests/fixtures/ai-steps-fake-openai/script.json` (UC265 markers) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Create and publish an agent; ask it about Ann | The reply streams with the SSN's last four, email, phone and account masked; "Ann Lee" stays |
| 2 | Read the thread | The stored reply is the masked one |
| 3 | Run a workflow whose Agent step summarises Priya | The step's summary is masked and names Priya |
| 4 | Turn redactPii off, publish, ask again | The reply is as the model wrote it |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-265-api.py` | `ISOLATED=1 make usecase-test UC=uc-265 LAYER=api` |
