# Add account is on the Accounts tab for whoever manages apps, and never for a member

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-703`.
Service: `tools-service` with platform-service and the console. Layers: ui. Guide: `docs/guide/plugins.md`, Several
accounts of one app. Design: the several accounts per app design, D1 and D10.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | An admin's Accounts tab has Add account in its toolbar, every row says where it points, and the page header adds no account | ui | 1 | 1 |
| S2 | Add account opens the Connect window asking the account's name first | ui | 2 | 2 |
| S3 | At 390 wide Add account sits under the search, which keeps its width | ui | 1 | 1 |
| S4 | A member sees the team's accounts with no Add account and no Rename or Delete | ui | 4 | 4 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Plugins | The `ops-ai-plugins` repository beside ops-ai, or `OPS_PLUGINS_REPO` |
| Fake Salesforce | `docs/usecases/lib/fake_salesforce.py` (Docker for its sign-in) |
| People | Priya Shah (team admin), Maya Okafor (member); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | Salesforce on as Retail org at kestrel's My Domain; EU org added at kestrel-eu's | Both made |
| 1 | Priya opens Salesforce › Accounts at 1440 and 390 | Add account enabled in the toolbar; no header Connect; rows read kestrel.my.salesforce.test and kestrel-eu.my.salesforce.test; at 390 the button is below a search wider than 200px |
| 2 | She presses Add account | The Connect window shows Account name |
| 3, 6 | Every page | No page errors |
| 4 | Maya opens the same tab at 1440 and 390 | No Add account; no row menu offers Rename or Delete |
| 5 | Maya opens Connectors › Mine | It opens |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 1 | Header Connect returning for a connected app (`lib/app-state.ts` headerActionFor) fails the header count; dropping the identity line fails the host text |
| 4 | Showing the toolbar button without `mayManage` (`components/connections/app-page.tsx`) fails the member's count |
| Disabled reason | `lib/app-state.test.ts` checks Add account is disabled with its reason while the auth config is missing or broken |

## Scripts

| Layer | Script |
|---|---|
| ui | `docs/usecases/tools-service/scripts/test-uc-703-ui.mjs` |
