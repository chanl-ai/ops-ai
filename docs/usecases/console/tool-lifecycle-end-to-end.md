# A bank API goes from import to a governed agent call

Status: current. Id: `uc-055`. Service: `console`. Layers: ui.

an earlier change's stories US1 to US5 in one run, as the seeded people, in the console. The design is
[tool lifecycle](../../architecture/tool-lifecycle.md).

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | James Richardson (builder) and Maya Okafor (approver) on Operations, Nadia Petrov (approver) on Security, Priya Shah (admin); password `northfield-demo` |
| The fake bank on https | the ui harness's `tools: { bank: true }`; its `/v1/openapi-open.json` lists `get_account` (GET) and `place_hold` (POST, with an example response) and names no security scheme |
| Agents granted from tools-service | the ui harness's `tools: { gateway: true }` starts the agents service with tools-service as its gateway |
| No model calls | the ui harness runs the agents service on the scripted model; a chat message `call <tool> <json>` calls that tool |

The run uses its own stack and database, not the shared stack on :3016, because the shared stack's agents service
calls a real model provider.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya allows the bank's host and range | 201 |
| 2 | James imports the open spec, selects `place_hold`, saves the draft | 201; `get_account` read, `place_hold` write; `place_hold`'s stub is the spec's example |
| 3 | James requests a security review from the module page | the module is in review |
| 4 | Nadia opens Reviews > Tool modules and approves | the module is published |
| 5 | James runs `get_account` and `place_hold` from the module's test panel, as its owner with no workflow approval | the read reaches the bank; the write answers from the stub (pending an earlier change T008 until it is on the stack) |
| 6 | James grants both operations to Branch Concierge, saves and publishes the agent | the agent holds `get_account` and `place_hold` |
| 7 | James asks Branch Concierge `call get_account {"accountId": "CHQ-2219"}` | the read runs; the reply is "Here is what I found." |
| 8 | James asks it `call place_hold {"accountId": "CHQ-2219"}` | an approval card shows; nothing reaches the bank |
| 9 | Maya opens Reviews and approves the held write | the write runs once (pending an earlier change T013: chat writes are listed in Reviews) |
| 10 | James opens the module's Activity tab | it lists the `get_account` call |
| 11 | James hides `get_account` and publishes; the agent's grant dialog lists it as no longer offered, with Remove | (pending an earlier change T010 and T011) |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-055-ui.mjs` | failing: steps 5, 9 and 11 wait on an earlier change T008, T013 and T010/T011 |

## Non-vacuous check

Each pending step fails today for the reason named in its check. Step 7's reply "Here is what I found." comes only
after a tool result; without the grant the scripted model answers "I could not find that.".
