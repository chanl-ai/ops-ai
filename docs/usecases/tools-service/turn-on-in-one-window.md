# An admin turns an app on in one window and everyone can use it

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-628`.
Service: `tools-service` with agents-service and platform-service. Layers: api, ui. Guide: `docs/guide/plugins.md`.
Design: the app set-up design (one Turn on window, two questions and one choice).

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | An admin turns Salesforce or GitHub on in one window: where the team signs in is asked once and fixed on Ops AI's auth config, tools use each person's own account with the team account for runs nobody started, the app's read tools are added, and the team's assistant gets them when the admin leaves the box ticked; someone without the permission can do none of it | api, ui | 1-4, 7-9 | 1, 2, 8 |
| S2 | The admin signs the team account in, the org address comes from the token, and a person who has not connected their own account meets the Connect card in chat, never the team account | api, ui | 5-6, 10 | 5, 10 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Plugins on | Each layer starts its services with `OPS_PLUGINS=true` and Ops AI's own app for each plugin (`OPS_PLUGIN_CLIENTS`) |
| The plugins | The `ops-ai-plugins` repository beside ops-ai at main, or `OPS_PLUGINS_REPO` naming a checkout |
| Fakes | `docs/usecases/lib/fake_salesforce.py` (sign-in on its My Domain, org address in the token answer) and the plugins repo's `github/tests/fake_github.py` |
| People | Sam Adeyemi (Security admin), Priya Shah (team_ops admin), James Richardson (builder), Ravi Menon (viewer); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya turns Salesforce on with each person's own account and the company's My Domain | The address reads fixed on Ops AI's auth config; the account signs in as each person with the team account for unattended runs; every read tool is added and no write tool |
| 2 | She gives the team's assistant Salesforce's read tools, then asks again | Given at once, exactly the read tools; the second time changes nothing |
| 3 | She turns GitHub on and gives the assistant its tools | Its two read tools, never its write tool |
| 4 | Ravi tries to turn an app off and to change the assistant's tools | Both refused 403 |
| 5 | Priya signs the team account in at the My Domain | Connected, with the org address from the token on the account's row |
| 6 | James, who has not connected his own Salesforce account, opens My accounts | Salesforce is listed and not connected |
| 7 | In the console, Priya opens Salesforce and presses Connect | One window: where you sign in, whose account tools use, and the assistant box, ticked |
| 8 | She allows access at the fake Salesforce | The window says Connected as the account, how many read tools were added and that the assistant got them |
| 9 | Ravi opens Salesforce's page | No Connect for him; the page says who can turn it on |
| 10 | James asks the assistant about a case in a new chat | The Connect card asks for his own Salesforce account |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 1 | The run starts on a fresh database, so the turn-on is a first one; the count of tools added is compared with the read tools on the app's page |
| 2 | The second call must answer `already` and leave the assistant's version as it was |
| 10 | The card must name Salesforce and the chat must not answer from the team account |

## Scripts

| Layer | Script |
|---|---|
| api | `docs/usecases/tools-service/scripts/test-uc-628-api.py` |
| ui | `docs/usecases/tools-service/scripts/test-uc-628-ui.mjs` |
