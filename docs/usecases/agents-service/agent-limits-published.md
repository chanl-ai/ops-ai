# A builder sets the limits callers override within and publishes them with the agent

Status: current. Id: `uc-088`. Service: `agents-service`. Layers: ui.

Callers (a banker in chat, a service on the API, a widget on a public key) may change some of an agent's settings,
but only inside limits the builder sets and a reviewer approves. This use case walks the agent page as a builder:
it offers only the controls the runtime acts on, saves the limits on a new version, refuses a limit that does not
hold together, and publishes the limits through the same review as the rest of the agent.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | picked per run by `make usecase-test` |

The script starts its own agents service on the scripted model and a console whose Agents call it. No model key is
needed. Publish requests are approved as they are made because `registry_auto_approve` is on in dev.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Create an agent granted `lookup_account` and `place_wire_hold`, publish v2, open two chats with it, open its page | The page loads with a Caller limits section |
| 2 | Look at Can talk on, Guardrails and the tabs | Chat is the only channel; only "Tool calls per turn" is shown; no Evals tab; Recent runs lists exactly the two chats `GET /v1/agents/{id}/runs` returns |
| 3 | Turn on temperature with highest 0.7 and default 0.9, make only `lookup_account` switchable, allow added instructions, save | 422 `invalid_limits`, message starting `limits.temperature.default`; the agent stays at v2 |
| 4 | Set the default to 0.4 and save | The draft over the published v1 (v2) with temperature 0 to 0.7 default 0.4, switchable `lookup_account`, added instructions allowed; history says "Changed caller limits" |
| 5 | Request publish of the draft | The review's `agentPublish.limits` equals the saved limits; the draft is published |
| 6 | In the Test panel, ask to hold wire W-88213 | Why names the review the write paused on, and says it needs a step-up exactly when the API's test turn does |
| 7 | Empty "Tool calls per turn", set "Model calls per turn" to 40, save | the saved caps are `maxToolCallsPerTurn: null` (no cap) and `maxModelCallsPerTurn: 40` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `agents-service/scripts/test-uc-088-ui.mjs` | written |

## Non-vacuous check

Step 3 is the refusal: without the server's limit check (`check_limits` in `routers/agents.py`) the save would make
v3 with a default outside its range. The API tests in `tests/api/test_agent_limits.py` were each watched failing with
the check, the review copy and the per-model publish check removed.
