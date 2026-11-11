# An account a workflow or agent names is not deleted until nothing names it

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-707`.
Service: `tools-service` with agents-service and platform-service. Layers: api, ui. Guide: `docs/guide/plugins.md`, Several
accounts of one app. Design: the several accounts per app design, added scope P7.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | An admin deleting an account that a published workflow step names is refused with the count, so no run is left naming a deleted account | api | 1-2 | 2 |
| S2 | An account only an agent names is not deleted either, and the refusal names that agent | api | 3 | 3 |
| S3 | Once neither the step nor the agent names it, the delete goes through | api | 4 | 4 |
| S4 | In the console, the delete says it is refused and why, and the row stays | ui | 1 | 1 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Plugins | The `ops-ai-plugins` repository beside ops-ai, or `OPS_PLUGINS_REPO` |
| Fakes | `docs/usecases/lib/fake_salesforce.py` through `docs/usecases/lib/several_accounts.py`, with agents-service and an engine worker |
| People | Priya Shah (team admin), Sam Adeyemi (Security admin); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya turns Salesforce on as Retail org, adds EU org, and publishes a workflow whose step names EU org | Published |
| 2 | She deletes EU org | Refused 409 `account_in_use`, counting 1 published version and naming the workflow; EU org is still listed |
| 3 | She publishes the workflow with the step naming Retail org, gives an agent EU org, and deletes EU org | Refused 409 `account_in_use` naming the agent and no workflow |
| 4 | The agent names Retail org; she deletes EU org | 204; EU org is gone |
| ui 1 | At 1440 and 390, with an agent naming EU org, Priya deletes it from its row's menu | The toast says EU org is named by one draft workflow or agent version and to change it first; the row stays |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 2 | With the check removed from `connections/service.py` `delete`, the delete answers 204 and step 2 fails; with agents-service's count reading another team or no published version, `published` is not 1 |
| 3 | With agents-service counting no agent versions in `account_uses_in`, the delete answers 204 and step 3 fails (seen) |
| 4 | The same account is deleted at the end, so a check that refuses every named account fails step 4 |

## Scripts

| Layer | Script |
|---|---|
| api | `docs/usecases/agents-service/scripts/test-uc-707-api.py` |
| ui | `docs/usecases/agents-service/scripts/test-uc-707-ui.mjs` |
