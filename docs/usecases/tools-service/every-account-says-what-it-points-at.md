# Every account row says what it points at, also for an app that declares nothing and a custom app

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-693`.
Service: `tools-service` with platform-service. Layers: api. Guide: `docs/guide/plugins.md`, Several accounts of one app.
Design: the several accounts per app design, section 2.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Each account row on an app's Accounts list says what it points at, for a plugin that declares no identity | api | 1 | 1 |
| S2 | A person's own accounts on Connectors › Mine say the same | api | 2 | 2 |
| S3 | A custom app's accounts say their addresses | api | 3 | 3 |

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
| 1 | GitHub with Platform server (github.test) and Corp server (ghe.corp.test) | Each row's `identity` starts with its server's host; the two differ |
| 2 | Maya signs in on Platform server and adds Corp · Maya at ghe.corp.test | `GET /v1/me/connections` lists both with their servers |
| 3 | A custom app with accounts at ledger.north.test and ledger.south.test | `GET /v1/apps/{app}/accounts` lists both by their address hosts |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 1-3 | With the identity builder's fallback returning nothing (`plugins/host.py` account_identity), every row's identity is empty and all three fail |

## Scripts

| Layer | Script |
|---|---|
| api | `docs/usecases/tools-service/scripts/test-uc-693-api.py` |
