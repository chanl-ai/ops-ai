# An agent runs in the account it names, and a step it starts runs in the step's

Status: draft. Step 1 passes; step 2 fails before any account is chosen, because a workflow an agent starts from a
chat is refused at its first tool call with `acting_for_refused` ("A member of this team with that email was not
found"), on PostgreSQL with platform sign-in. That refusal is a separate defect, not part of several accounts. Id:
`uc-696`. Service: `agents-service` with tools-service, platform-service and an engine worker. Layers: api. Guide:
`docs/guide/plugins.md`, Several accounts of one app. Design: the several accounts per app design, AC3 and AC11.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | An agent that names EU org answers a chat query in the EU org, and the call's log row names the EU account | api | 1 | 1 |
| S2 | A workflow the agent starts, whose step names Retail org, runs that step in Retail org: the step's choice wins over the agent's | api | 2 | 2 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Plugins | The `ops-ai-plugins` repository beside ops-ai, or `OPS_PLUGINS_REPO` |
| Fake Salesforce | `docs/usecases/lib/fake_salesforce.py` (production and EU orgs), through `docs/usecases/lib/several_accounts.py` |
| People | Priya Shah (team admin); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Agent "Case desk" holds `salesforce_query` and `accounts: {plugin:opsai.salesforce: EU org}`; Priya writes `call salesforce_query {...}` in its chat | The EU org answers; the call row's `connectionId` is EU org's |
| 2 | Priya writes `call workflow__uc696_retail {}`; that workflow's step names Retail org | The production org answers; the row names Retail org |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 1 | Without the agent's map in `graphs/agent_wrapper.py` turn_accounts, the query reaches the production org (the team default) |
| 2 | With the merge order in `api/engine_host.py` merged_accounts reversed, the agent's EU org wins and the query reaches the EU org |

## Scripts

| Layer | Script |
|---|---|
| api | `docs/usecases/agents-service/scripts/test-uc-696-api.py` |
