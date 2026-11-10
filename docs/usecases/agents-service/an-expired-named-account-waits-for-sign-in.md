# An expired sign-in on an account a step, agent or chat names waits for a new sign-in and never uses another account

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-708`.
Service: `agents-service` with tools-service and platform-service. Layers: api. Guide: `docs/guide/plugins.md`, Several
accounts of one app. Design: the several accounts per app design.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A call naming an account whose sign-in expired is refused for a new sign-in of that account and never sent to the team's other account | api | 1 | 1 |
| S2 | A workflow run whose step names it waits with that reason | api | 2 | 2 |
| S3 | A chat whose agent names it gets the sign-in card | api | 3 | 3 |
| S4 | Once an admin signs it in again, the waiting run goes on in that account | api | 4 | 4 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Plugins | The `ops-ai-plugins` repository beside ops-ai, or `OPS_PLUGINS_REPO` |
| Fakes | `docs/usecases/lib/fake_salesforce.py` (production and EU orgs; Docker for its sign-in), through `docs/usecases/lib/several_accounts.py` |
| People | Priya Shah (team admin); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Retail org (the default) and EU org; EU org's sign-in expires (401, refresh refused); two calls name EU org | Both refused naming EU org; EU org reads expired; no query reaches Retail org |
| 2 | A published workflow whose step names EU org runs | The run waits, its reason naming EU org; no query reaches Retail org |
| 3 | A chat with an agent naming EU org asks for a query | The turn carries the sign-in card naming EU org; no query reaches Retail org |
| 4 | Priya signs EU org in again | The waiting run succeeds, its query on EU org |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 1 | With an expired named account falling back to the team's default, the query reaches Retail org |
| 2 | With the expired refusal not read as a sign-in wait (`connect_wait`), the run succeeds or fails instead of waiting |
| 4 | With the team's new sign-in reporting no connected event, the run waits forever |

## Scripts

| Layer | Script |
|---|---|
| api | `docs/usecases/agents-service/scripts/test-uc-708-api.py` |
