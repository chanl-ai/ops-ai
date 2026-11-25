# Changing who signs in to each person makes calls act as the person, and schedules keep the shared login

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-709`.
Service: `tools-service` with platform-service. Layers: api. Guide: `docs/guide/plugins.md`, Several accounts of one app.
Design: the several accounts per app design.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | After an admin changes an account from the shared team login to each person, a call naming it for a person signs in as that person, and a call acting for nobody keeps the team's login | api | 1-4 | 3 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Plugins | The `ops-ai-plugins` repository beside ops-ai, or `OPS_PLUGINS_REPO` |
| Fakes | `docs/usecases/lib/fake_salesforce.py` (production and EU orgs; Docker for its sign-in), through `docs/usecases/lib/several_accounts.py` |
| People | Priya Shah (team admin), Maya Okafor (member); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Retail org and EU org, both on the shared team login; a call names EU org for Maya | The fake sees the team's login at EU org |
| 2 | Priya changes EU org to Each person signs in; Maya signs in | The row reads `person` and counts one person signed in |
| 3 | A call names EU org for Maya | The fake sees Maya's own login, at EU org |
| 4 | A call names EU org for nobody, as a schedule's does | Refused `CONNECTION_NOT_LINKED`; the fake sees no call |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 3 | With `PluginHost` ignoring the account's `sign_in` and always using the team login, the fake sees the team's login |
| 4 | With the team login used as a backup for each person, the fake sees the team's login |

## Scripts

| Layer | Script |
|---|---|
| api | `docs/usecases/tools-service/scripts/test-uc-709-api.py` |
