# Callers from before several accounts keep working

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-705`.
Service: `tools-service` with platform-service. Layers: api, sdk. Guide: `docs/guide/plugins.md`, Several accounts of one
app. Design: the several accounts per app design, AC10.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A call naming its account with the older single `runContext.account` string still runs there, and the newer map wins when both are sent | api | 1-2 | 1 |
| S2 | The older bodyless add of a person's second account still starts a sign-in where their first account signs in | api | 3 | 3 |
| S3 | The Python SDK from before this change reads account rows that now carry `identity`, and makes the bodyless add | sdk | 4-5 | 4 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Plugins | The `ops-ai-plugins` repository beside ops-ai, or `OPS_PLUGINS_REPO` |
| Fake Salesforce | `docs/usecases/lib/fake_salesforce.py`, through `docs/usecases/lib/several_accounts.py` |
| The older SDK | `git archive 13ada62b sdk/python/src`, unpacked by the sdk script |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | A call with `runContext.account: EU org`; one with that and `accounts: {salesforce: Retail org}` | The EU org; then the production org |
| 2 | `runContext.account: Ghost org` | 404 ACCOUNT_NOT_FOUND |
| 3 | Maya posts `/v1/me/accounts/{id}/another` with no body | A sign-in at the first account's My Domain |
| 4 | The older SDK reads Salesforce's page | Both team accounts, each row carrying `identity` |
| 5 | The older SDK's `apps_add_own_account(id)` | A sign-in at the first account's My Domain |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 1 | Dropping the read of `runContext.account` in `gateway_calls.py` makes the first call run on Retail org |
| 3, 5 | The fake refuses a token at any other org's host, and egress refuses an address the account does not hold |

## Scripts

| Layer | Script |
|---|---|
| api | `docs/usecases/tools-service/scripts/test-uc-705-api.py` |
| sdk | `docs/usecases/tools-service/scripts/test-uc-705-sdk.py` |
