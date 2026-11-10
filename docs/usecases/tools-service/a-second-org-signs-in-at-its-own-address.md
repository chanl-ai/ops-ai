# A second live org signs in at its own address and a call naming it reaches it

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-691`.
Service: `tools-service` with platform-service. Layers: api. Guide: `docs/guide/plugins.md`, Several accounts of one app.
Design: the several accounts per app design, failure mode C1.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A team on Ops AI's app adds a second live Salesforce org at its own My Domain; it signs in there and keeps that org's address, and the first account keeps its own | api | 1-2, 4-5 | 2 |
| S2 | A call naming the second org reaches it; a call naming no account stays on the team's default | api | 3-4 | 3 |

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
| 1 | Priya turns Salesforce on through Ops AI's app as Retail org at the production org's My Domain and signs in | Retail org keeps the production org's address |
| 2 | She adds EU org typing the EU org's My Domain and signs in | The sign-in opens at the EU My Domain; EU org keeps the EU org's address |
| 3 | A run calls salesforce_query naming EU org (`runContext.accounts`) | The EU org answers it |
| 4 | A run calls it naming no account | The production org answers; Retail org's address is unchanged |
| 5 | Ops AI's auth config | Holds the first address as a default, not fixed |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 2 | With the first turn-on saving the address as fixed (`plugins/routes.py` `_fix_first_place`), the second sign-in opens at the production org and steps 2, 3 and 5 fail |
| 3 | The fake answers a token only at its own org's host, so a call sent to the wrong org is refused |

## Scripts

| Layer | Script |
|---|---|
| api | `docs/usecases/tools-service/scripts/test-uc-691-api.py` |
