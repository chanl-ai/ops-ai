# A workflow's write is checked against the team's sending policy before it goes out

Status: current. Id: `uc-266`. Service: `tools-service`. Layers: api. Card: c-300.

With a team's check before sending on, the tool gateway judges each write that carries no approval against the team's
newest sending policy before it runs. A write the policy forbids is refused as `needs_review` with the reason: a
workflow's tool step leaves by its `refused` port, and an agent's turn pauses for approval. The setting is off until a
team turns it on.

## Preconditions

| Needs | How |
|---|---|
| platform-service, models-service on the fake OpenAI, tools-service on its own model key, agents-service and a worker | the script's stack |
| The judge's answers | `services/agents-service/tests/fixtures/ai-steps-fake-openai/script.json` ("Outgoing open_case" rules) |
| Priya Shah, admin of team_ops | the platform dev seed |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | Save and publish a workflow that opens a case through the gateway | live |
| 1 | Save the team's sending policy (no refunds promised) | v1 |
| 2 | With the setting off, run it with a subject that promises a refund | the case opens |
| 3 | Priya turns check before sending on | 200 |
| 4 | Run it again with a refund promise | held: the step leaves by refused with "promises a refund" |
| 5 | Run it with an allowed subject | the case opens |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-266-api.py` | `ISOLATED=1 make usecase-test UC=uc-266 LAYER=api` |
