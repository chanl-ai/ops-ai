# A package app runs on the chosen org and never on one without the package

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-706`.
Service: `tools-service` with platform-service. Layers: api. Guide: `docs/guide/plugins.md`, Package apps.
Design: the several accounts per app design, added scope P8.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A team turns on a package app that runs inside Salesforce; a call naming the org that has the package reads its record there | api | 1-3 | 3 |
| S2 | Sign-in checks each org for the package; a call on an org without it is refused before it reaches the org | api | 2, 4 | 4 |
| S3 | A call that names an account under the package's own app, which has none, is refused, never defaulted | api | 5 | 5 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Plugins | The `ops-ai-plugins` repository beside ops-ai, or `OPS_PLUGINS_REPO`, and the fictional Loan desk package in `docs/usecases/lib/plugins/loan_desk` |
| Fakes | `docs/usecases/lib/fake_salesforce.py`: the loan object is installed in the EU org only; Docker for its sign-in |
| People | Priya Shah (team admin), Sam Adeyemi (Security admin); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya turns Salesforce on as Retail org (production), adds EU org, and turns Loan desk on | Loan desk is on with no account of its own |
| 2 | Each org's sign-in runs its test | Retail org's account lists the loan object as missing; EU org's lists nothing missing |
| 3 | A run calls loan_desk_get_loan naming EU org under Salesforce (`runContext.accounts`) | The EU org answers with the loan, signed in with EU org's account |
| 4 | A run calls it naming no account (the team default, Retail org) | Refused with PACKAGE_MISSING naming Retail org; the fake receives no request |
| 5 | A run names EU org under Loan desk's own app id | Refused with ACCOUNT_NOT_FOUND; the fake receives no request |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 2 | The fake answers NOT_FOUND for the loan object at the production org only, so a check that reads nothing, or reads one org for both, fails one of the two |
| 3 | The fake answers a token only at its own org's host; with the package signing in through its own binding (`for_call` choosing with the package instead of the app it runs on) the call has no account and fails |
| 4 | With `missing_objects` returning nothing, the call reaches the production org and the fake records it |

## Scripts

| Layer | Script |
|---|---|
| api | `docs/usecases/tools-service/scripts/test-uc-706-api.py` |
