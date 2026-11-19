# Two accounts of one app with one owner never share a name

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-699`.
Service: `tools-service` with platform-service. Layers: api. Guide: `docs/guide/plugins.md`, Several accounts of one app.
Design: the several accounts per app design, S4.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Two adds of one name at the same moment make one account; the other is refused 409 account_name_taken | api | 1 | 1 |
| S2 | A name differing only in case and a rename are refused the same way; a person's own account may take a team account's name, since names are unique per owner | api | 2-4 | 3 |
| S3 | A lookup by the name finds exactly one account | api | 5 | 5 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Plugins | The `ops-ai-plugins` repository beside ops-ai, or `OPS_PLUGINS_REPO` |
| Fakes | `docs/usecases/lib/fake_salesforce.py` (production, EU and sandbox orgs; Docker for its sign-in) and `docs/usecases/lib/fake_github.py`, through `docs/usecases/lib/several_accounts.py` |
| People | Priya Shah (team admin), Maya Okafor (member), Sam Adeyemi (Security admin); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Two adds of EU org N at once, four rounds | One 201 and one 409 account_name_taken each round |
| 2 | An add named eu ORG 0 | 409 account_name_taken |
| 3 | Maya's own second account named EU org 0 | Its sign-in starts: names are unique per owner, and the team holds EU org 0 |
| 4 | Retail org renamed to EU ORG 1 | 409 account_name_taken |
| 5 | `GET /v1/apps/{app}/accounts?name=eu org 0` | One account |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 1, 4, 5 | Without the filtered unique index (migration `0071_account_key`) both adds succeed every round and the rename passes |
| 3 | With names unique per team (before migration `0076_account_owner_key`), Maya's add is refused 409 |
| All | SQL Server: the index is filtered (`mssql_where`) and the key is a stored column; this script has not been run on SQL Server (`make uc-sql-server` starts a remote machine) |

## Scripts

| Layer | Script |
|---|---|
| api | `docs/usecases/tools-service/scripts/test-uc-699-api.py` |
