# The model is told the account each app uses and cannot switch it in words

Status: current on main behind the `OPS_PLUGINS` switch. Id: `uc-704`. Service: `agents-service` with tools-service
and platform-service, on the scripted model. Layers: api. Guide: `docs/guide/plugins.md`, Several accounts of one app.
Design: the several accounts per app design, D7 and AC9.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | With EU org chosen for a chat, the model's apps line names it and what it points at | api | 1 | 1 |
| S2 | A person asking in words for another org changes nothing: the call still runs in the chosen org | api | 2 | 2 |
| S3 | No tool takes an account input, so the model cannot pick one | api | 3 | 3 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Plugins | The `ops-ai-plugins` repository beside ops-ai, or `OPS_PLUGINS_REPO` |
| Fake Salesforce | `docs/usecases/lib/fake_salesforce.py`, through `docs/usecases/lib/several_accounts.py` |
| Scripted model | Answers "Which apps can you reach?" with the apps line it was given (`services/agents-service/tests/conftest.py`) |
| People | Priya Shah (team admin); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | The team's default agent holds `salesforce_query`; the chat picks EU org with `PUT /chat/threads/{id}/connectors`; Priya asks "Which apps can you reach?" | The reply carries "Salesforce: on · uses EU org (<EU host>)" |
| 2 | Priya writes "Use the retail org." and calls `salesforce_query` | The EU org answers |
| 3 | `GET /v1/tools/salesforce_query` | Its input schema has no account field |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 1 | With the account dropped from `api/apps_line.py` describe, the line reads "Salesforce: on" only |
| 2 | Without the chat's pick in `graphs/agent_wrapper.py` turn_accounts, the query reaches the production org |

## Scripts

| Layer | Script |
|---|---|
| api | `docs/usecases/agents-service/scripts/test-uc-704-api.py` |
