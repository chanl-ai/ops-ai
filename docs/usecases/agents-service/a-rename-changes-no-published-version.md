# Renaming an account changes no published version, and the next publish names the dead name

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-701`.
Service: `agents-service` with tools-service, platform-service and an engine worker. Layers: api. Guide:
`docs/guide/plugins.md`, Several accounts of one app. Design: the several accounts per app design, B2 and B3.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Before a rename, the warning counts the published versions naming the account | api | 1 | 1 |
| S2 | A rename leaves the published version as it was: same digest, and its run is refused rather than sent elsewhere | api | 2 | 2 |
| S3 | Publishing a version that still names the old name is refused; naming the new one publishes and runs | api | 3-4 | 3 |

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
| 1 | A published workflow names EU org; `GET /v1/workflows/definitions/account-uses?app=…&name=EU org` | published 1, naming the workflow |
| 2 | EU org is renamed Europe org; the workflow runs | The live digest is unchanged; nothing reaches Salesforce |
| 3 | A new version still naming EU org is published | 422 account_name_unknown |
| 4 | A version naming Europe org is published and run | Approved; the EU org answers |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 3 | Without the publish check in `api/engine_lifecycle.py` request_publish, the version naming the dead name publishes |
| 2 | A rename that rewrote definitions would change the live digest |

## Scripts

| Layer | Script |
|---|---|
| api | `docs/usecases/agents-service/scripts/test-uc-701-api.py` |
