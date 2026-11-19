# An app's page shows one state and its next action

Status: current. Id: `uc-674`. Service: `tools-service` with platform-service. Layers: ui. Guide:
`docs/guide/apps.md` (An App's state).

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | An admin opens an app the team has no auth config for: it says to add one, the button opens the new auth config, saving it signs nobody in, and Turn on then saves; the header and Settings read the same state at each point | ui | 1-2 | 2 |
| S2 | An admin turns an app off: its header and Settings both read off, and Turn on in Settings puts it back on as it was, with no sign-in | ui | 3 | 3 |
| S3 | Anyone who opens an app the install does not hold reads that it isn't installed and who installs apps, with no failed request | ui | 4 | 4 |
| S4 | Every app page opens with no console error, for an admin and a member of each team, and a member reads their own state | ui | 5-6 | 5 |
| S6 | A state change on an app's page shows the same words on Mine and in the chat picker | ui | 8 | 8 |
| S7 | Someone who cannot set an app up reads one line on Mine, not set up and ask an admin, and sees no Settings tab | ui | 9 | 9 |
| S8 | Words follow the reader's role and say whose state they are: an admin's picker offers the team's step, a viewer's asks a named person of the team who manages its apps, a per-person app's header says You and its team row Team account, and a missing app's page asks for no resources and tells the admin how apps are installed | ui | 10 | 10 |
| S9 | Every app name in the chat picker reads in full, for a member and an admin, at 1440 and 390 wide | ui | 11 | 11 |
| S5 | A viewer sees no auth config on an app's page: no Auth configs tab, no Auth config column, no config name; an admin sees the column on the accounts a config's count opens | ui | 7 | 7 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The plugins | The `ops-ai-plugins` repository beside ops-ai at main, or `OPS_PLUGINS_REPO` naming a checkout |
| Plugins on | tools-service starts with `OPS_PLUGINS=true`, GitHub and Salesforce on `OPS_PLUGIN_PATHS`, and Ops AI's own app for Salesforce only (`OPS_PLUGIN_CLIENTS`) |
| People | Sam Adeyemi (Security admin), Nadia Petrov (Security approver), Priya Shah (Operations admin), Ravi Menon (Operations viewer); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | Priya turns Salesforce on for Operations through the API | 200 |
| 1 | Sam opens GitHub's page | The header reads Needs an auth config with Add an auth config; Settings says "GitHub is off, with no auth config yet"; no failed call |
| 2 | He adds an auth config from the header, then presses Turn on and Turn on in the window | Saving the config opens no window and the header reads Available with Turn on; after Turn on the header reads Needs sign-in and Settings "GitHub is on" |
| 3 | Priya opens Salesforce › Settings, presses Turn off and confirms, then Turn on in Settings | Off: the header reads Available with Turn on and Settings "Salesforce is off"; on again: Settings "Salesforce is on" in the state it had, no sign-in window |
| 4 | Priya opens `plugin:acme.ticketdesk`, a plugin the install does not hold | The header reads Not installed and the page says it isn't installed and to ask the person who runs Ops AI at the company; no failed call |
| 5 | Sam, Nadia, Priya and Ravi each open GitHub, Salesforce and the missing plugin | Zero page errors, console errors and failed /v1 calls on each of the 12 pages |
| 6 | Nadia opens GitHub | Her own state, Needs sign-in, with Sign in from Mine |
| 8 | Priya turns Salesforce off on its page, then on | Off: the page, her Mine card and the chat picker all read Available; on again, read with no reload: Mine and the chat picker read what the page reads |
| 9 | Ravi (viewer) opens Mine and GitHub's page | His GitHub card reads Not set up for your team yet with Ask an admin and nothing else; the page has no Settings tab |
| 10 | Priya and Ravi open the chat picker and Mine; Nadia opens GitHub; Priya and Ravi open the missing plugin's Resources | Priya's GitHub row offers Set up, Ravi's says ask an admin; Ravi's Mine names someone who manages Operations' apps in Operations (James Richardson or Priya Shah), never an admin of every team; Nadia's header reads You: and the account row Team account:; the Resources tab says it isn't installed with no failed call, and only Priya reads how apps are installed |
| 11 | Ravi and Priya open the chat picker at 1440 and at 390 wide | Every row's app name is shown whole, none cut short; Ravi's rows at 1440 include one that says ask an admin, with that line under the name |
| 7 | Ravi (viewer) and Priya (admin) open Salesforce's Accounts; Priya then presses a config's account count on Auth configs | Ravi: no Auth configs tab, no Auth config column, no config named; Priya: the Auth configs tab, no Auth config column on the plain list, and the column on the list her count opens |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `tools-service/scripts/test-uc-674-ui.mjs` | passing |

## Non-vacuous check

Steps 1 to 4 fail on main 48c22f60: GitHub's page called `GET /v1/apps/plugin:opsai.github/update` (404) and its
picker was disabled with no reason, Settings said "Salesforce is on" after Turn off, and the missing plugin's page
answered 404.

Step 11 fails while the picker keeps the ask-an-admin line beside the name above the phone breakpoint: the picker is
the same fixed width at every screen width, so at 1440 a member's names were cut to a letter or two.

Step 7 fails with the Auth config column shown on every admin's Accounts list (the column's `config` gate removed
from `app-accounts-tab.tsx`): the plain list then counts one Auth config column where it should count none.
