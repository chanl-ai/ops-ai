# An admin turns an app on in one window and everyone can use it

Status: current on main behind the `OPS_PLUGINS` switch, which every layer turns on for its own services. Id: `uc-628`.
Service: `tools-service` with agents-service and platform-service. Layers: api, ui. Guide: `docs/guide/plugins.md`.
Design: the app set-up design (one Turn on window, two questions and one choice).

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | An admin turns Salesforce or GitHub on in one window: where the team signs in is asked once and fixed on Ops AI's auth config, tools use each person's own account with the team account for runs nobody started, the app's read tools are added, and the team's assistant gets them when the admin leaves the box ticked. Turn on saves and opens no sign-in window; connecting an account is an optional button after it. Someone without the permission can do none of it | ui | 1-4, 7-9 | 2 |
| S3 | On Connectors › Mine, an app the team has not set up never leads to a 404: a member reads Not set up for your team yet with the admins to ask and stays on Mine, and an admin's Turn on opens the app's own page | ui | 11-12 | 11 |
| S2 | The admin signs the team account in, the org address comes from the token, and a person who has not connected their own account meets the Connect card in chat, never the team account | api | 5-6, 10 | 5 |

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
| 7 | In the console, Priya opens Salesforce and presses Turn on | One window: where you sign in, whose account tools use, and the assistant box, ticked |
| 8 | She presses Turn on in the window | The team's setting is saved and no sign-in window opens; the window says Saved, how many read tools were added and that members connect their own account from Connectors › Mine |
| 8b | She presses Connect the team account and allows access at the fake Salesforce | The window says Connected as the account and that the assistant got the read tools |
| 9 | Ravi, a viewer, opens Salesforce's page | No Connect or Turn on: the page offers only Sign in from Mine |
| 10 | James asks the assistant about a case in a new chat | The Connect card asks for his own Salesforce account |
| 11 | Before Salesforce is on, Ravi (a member) opens Connectors › Mine and clicks the Salesforce card | The card and its details say Not set up for your team yet and Ask an admin, with no link to the app's page; he stays on Mine |
| 12 | Priya opens Connectors › Mine and presses Turn on on the Salesforce card | The app's page opens at /integrations/apps/plugin%3Aopsai.salesforce with Turn on, never a 404 |

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 1 | The run starts on a fresh database, so the turn-on is a first one; the count of tools added is compared with the read tools on the app's page |
| 2 | The second call must answer `already` and leave the assistant's version as it was |
| 10 | The card must name Salesforce and the chat must not answer from the team account |
| 8 | Popups are counted from before Turn on is pressed until the saved state shows, and the app's account must exist after it |
| 11-12 | The admin's page is checked for the app's own Turn on button and the member's for the absence of any link to the app's page |

## Scripts

| Layer | Script |
|---|---|
| api | `docs/usecases/tools-service/scripts/test-uc-628-api.py` |
| ui | `docs/usecases/tools-service/scripts/test-uc-628-ui.mjs` |
