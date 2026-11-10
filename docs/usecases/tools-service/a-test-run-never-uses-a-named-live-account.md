# A test run that names a live account uses the test account or is refused

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-700`.
Service: `tools-service` with platform-service. Layers: api. Guide: `docs/guide/plugins.md`, Several accounts of one app.
Design: the several accounts per app design, S7.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A live run naming EU org runs there; a test run naming it runs on the app's test account | api | 1-2 | 2 |
| S2 | With no test account, a test run naming a live account is refused SANDBOX_REQUIRED | api | 3 | 3 |

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
| 1 | Retail org, EU org and the UAT sandbox; a live run names EU org | The EU org answers |
| 2 | A test run names EU org | The sandbox answers; the call's log row is test, on the UAT account |
| 3 | UAT is deleted; a test run names EU org | 409 SANDBOX_REQUIRED; nothing is sent |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 2, 3 | Without the test-run rule in `PluginHost._named`, the test run's query reaches the EU org |

## Scripts

| Layer | Script |
|---|---|
| api | `docs/usecases/tools-service/scripts/test-uc-700-api.py` |
