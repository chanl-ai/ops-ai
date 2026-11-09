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
| S5 | A viewer sees no auth config on an app's page: no Auth configs tab, no Auth config column, no config name | ui | 7 | 7 |

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
| 7 | Ravi (viewer) and Priya (admin) open Salesforce's Accounts | Ravi: no Auth configs tab, no Auth config column, no config named; Priya: both |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `tools-service/scripts/test-uc-674-ui.mjs` | passing |

## Non-vacuous check

Steps 1 to 4 fail on main 48c22f60: GitHub's page called `GET /v1/apps/plugin:opsai.github/update` (404) and its
picker was disabled with no reason, Settings said "Salesforce is on" after Turn off, and the missing plugin's page
answered 404.
