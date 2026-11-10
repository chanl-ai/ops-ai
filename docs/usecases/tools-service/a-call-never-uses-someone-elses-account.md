# A call naming another person's own account or another team's account is refused

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-694`.
Service: `tools-service` with platform-service. Layers: api. Guide: `docs/guide/plugins.md`, Several accounts of one app.
Design: the several accounts per app design, B1.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | One person's own account signs only that person's calls: a run acting for nobody or for someone else that names it is refused, and nothing is sent | api | 1-3 | 2, 3 |
| S2 | The person's own call naming it runs in it | api | 4 | 4 |
| S3 | Another team's account is never found by name | api | 5 | 5 |

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
| 1 | Salesforce on with each person's own account beside the team's; Maya adds Mobile org · Maya of her own at the EU org | It signs in at the EU org |
| 2 | A run acting for nobody names Mobile org · Maya | 403 ACCOUNT_NOT_YOURS; no query reaches Salesforce |
| 3 | A run acting for Priya names it | 403 ACCOUNT_NOT_YOURS; nothing is sent |
| 4 | A run acting for Maya names it | It runs in the EU org |
| 5 | The Platform team has Brand org; a run in Operations names it | 404 ACCOUNT_NOT_FOUND; nothing is sent |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 2, 3 | With the own-account check removed from `PluginHost._named`, the call is sent on Maya's account |
| 5 | With an unknown name falling back to the default, the call runs on Retail org |

## Scripts

| Layer | Script |
|---|---|
| api | `docs/usecases/tools-service/scripts/test-uc-694-api.py` |
