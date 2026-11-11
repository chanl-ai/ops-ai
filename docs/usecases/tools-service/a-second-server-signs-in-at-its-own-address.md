# A second account of an app that is not Salesforce signs in at its own server

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-692`.
Service: `tools-service` with platform-service. Layers: api. Guide: `docs/guide/plugins.md`, Several accounts of one app.
Design: the several accounts per app design.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | On GitHub, which declares no identity setting and reads nothing from its token answer, a second account at a company's own server signs in there | api | 1 | 1 |
| S2 | A call naming that account acts with that server's sign-in; a call naming none stays on the default | api | 2-3 | 2 |

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
| 1 | Priya turns GitHub on as Platform server at github.test, then adds Corp server at ghe.corp.test and signs in | The sign-in opens at ghe.corp.test; each server issues one token |
| 2 | A run calls github_list_issues naming Corp server | The corp server's issue 412 |
| 3 | A run calls it naming no account | github.test's issue 7 |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 1, 2 | With the first account's address copied over the one typed (`plugins/routes.py` add_account), the sign-in opens at github.test and the call answers issue 7 |
| 2 | The fake's API answers each token with the issue of the server that issued it, so the wrong account shows the other server's issue |

## Scripts

| Layer | Script |
|---|---|
| api | `docs/usecases/tools-service/scripts/test-uc-692-api.py` |
