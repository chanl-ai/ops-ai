# A call naming an account that no longer exists is refused, never sent to the default

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-698`.
Service: `tools-service` with platform-service. Layers: api. Guide: `docs/guide/plugins.md`, Several accounts of one app.
Design: the several accounts per app design.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A call naming a deleted account is refused ACCOUNT_NOT_FOUND and never runs on the team's default | api | 1-2 | 2 |

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
| 1 | Retail org and EU org; a run names EU org | The EU org answers |
| 2 | EU org is deleted; a run names it again | 404 ACCOUNT_NOT_FOUND; nothing reaches Retail org |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 2 | With an unknown name falling back to the team's default in `PluginHost._named`, the query runs on Retail org |

## Scripts

| Layer | Script |
|---|---|
| api | `docs/usecases/tools-service/scripts/test-uc-698-api.py` |
