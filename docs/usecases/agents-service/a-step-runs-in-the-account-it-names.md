# A workflow step that names an account runs in that account

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-695`.
Service: `agents-service` with tools-service, platform-service and an engine worker. Layers: api. Guide:
`docs/guide/plugins.md`, Several accounts of one app. Design: the several accounts per app design, B2 and B3.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A published workflow whose tool step names EU org runs its query in the EU org, through the engine, the worker and the gateway | api | 1 | 1 |
| S2 | The same step naming none runs in the team's default | api | 2 | 2 |
| S3 | A step naming an account the team does not have cannot be published | api | 3 | 3 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Plugins | The `ops-ai-plugins` repository beside ops-ai, or `OPS_PLUGINS_REPO` |
| Fake Salesforce | `docs/usecases/lib/fake_salesforce.py` (production and EU orgs; Docker for its sign-in), through `docs/usecases/lib/several_accounts.py` |
| People | Priya Shah (team admin); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Retail org (default) and EU org; a workflow whose `ops.action.tool` step sets `accounts: {plugin:opsai.salesforce: EU org}` is published and run live | The EU org answers the query |
| 2 | The same workflow with no `accounts` | The production org answers |
| 3 | A step naming Ghost org is published | 422 account_name_unknown |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 1 | Without the step's map passed through `ToolPort.call` (`ops_engine/compiler.py` gateway_call), the query reaches the production org |
| 3 | The publish check (`api/account_names.py`) asks tools-service; without it the step publishes |

## Scripts

| Layer | Script |
|---|---|
| api | `docs/usecases/agents-service/scripts/test-uc-695-api.py` |
