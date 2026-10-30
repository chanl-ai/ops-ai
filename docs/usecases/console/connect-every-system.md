# A team admin connects every system for real, from one grid

Status: draft. Id: `uc-580`. Service: `console`. Layers: ui. Card: an earlier change.

Connections in the console showed sample data, so an admin could look at systems but not connect one. With the switch
`NEXT_PUBLIC_OPS_REAL_CONNECTIONS` on, Connections is a grid of the team's real systems, read from tools-service's
`GET /v1/systems` through the generated SDK (`apps/console/src/lib/api/ops-sdk.ts`). Each card is one system: a
plugin, a connection with the modules that use it, or a module with no connection yet. The API joins each card, so the
console never joins lists itself. With the switch off, the default, the shipped page shows and nothing here is called.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | An admin opens Connections and sees the team's systems as cards, each with its category, line and both environments | ui | 1-2 | 2 |
| S2 | Nothing of another team's reaches the grid | ui | 3 | 3 |
| S3 | Search and the category filter find a system, and the grid fits a phone | ui | 4-5 | 5 |
| S4 | With the switch off, the shipped page shows and the systems are never asked for | ui | 7 | 7 |
| S5 | An admin connects a new system from one dialog: a wrong key says Failed with the system's 401, the right one Working, and Save keeps it with the key sealed | ui | 8-10 | 10 |
| S6 | A system whose test fails and is cancelled leaves nothing behind | ui | 11 | 11 |
| S7 | A tool module connected from its card becomes one card with its connection | ui | 12 | 12 |
| S8 | On a connection's page, each environment shows its last test, and Edit keys changes a key the next test reads | ui | 14 | 14 |
| S9 | A plugin connects from its card with only what it needs: a key, never the header the plugin fixes | ui | 15 | 15 |
| S10 | A team admin writes the sending policy where Check before sending is turned on, and each save is a version | ui | 18 | 18 |
| S11 | An operation's mock answers are a list with a default, and a run against the mock gets the one that matches | ui | 19 | 19 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| For step 15: plugins on with the an earlier change header-key test plugin, and the fake system | `tools: { env: { ...fake.settings, OPS_PLUGINS: 'true', OPS_PLUGIN_PATHS } }` |
| The ui stack with platform sign-in, the bank stand-in and the switch on | `withUiStack(..., { platform: true, tools: { bank: 'core' }, consoleSwitches: { NEXT_PUBLIC_OPS_REAL_CONNECTIONS: '1' } })`; `allowBank` lists its host |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | Priya (Operations admin) creates Claims core (Core insurance) and Ledger (Finance); Sam creates Vault for Security | Three connections, 201 each |
| 1 | Priya opens Connections | A grid; the Claims core card shows its name, category, line and a test and a production row |
| 2 | Watch the requests | `GET /v1/systems` goes to tools-service with the session token and `X-Team-Id: team_ops` |
| 3 | Look for Vault | Not on the grid |
| 4 | Search "ledger", then clear it and pick Core insurance | Only Ledger, then only Claims core |
| 5 | Open Connections at 375 px | The grid fits with no sideways scroll |
| 6 | Throughout | No page errors |
| 8 | Connect a system: name Bank API, API key, the bank stand-in's address, test address /auth/api-key and a wrong key; Run test | Failed, 401 |
| 9 | Type the right key over it; Run test | Working, 200 |
| 10 | Save | The dialog closes; one card, test set and Working; the key field reads Sealed and the key shows nowhere |
| 11 | Connect a system with test address /no-such-page; Run test; Cancel | Failed, 404; the system the test made is deleted |
| 12 | Make a module with no connection; Connect on its card; fill the bank's key; Run test; Save | One connection card holds the module; no module card is left |
| 13 | Open the dialog at 375 px | It fits with no sideways scroll |
| 18 | Govern › Policies: type the sending policy in the card right after Check before sending; Save | Saved as a version with Priya's name; `GET /v1/send-policy` returns the text |
| 19 | Open the module's operation page; Add answer: Bank down, status 503, body {"error": "down"}, Default; Save; run the operation against the mock | Listed as Bank down, Default, Answers 503; the run answers 503 with the body |
| 15 | A stack with plugins on and the fake system (`docs/usecases/lib/fake_multi_auth.py`): Security installs the header-key test plugin; Priya presses Connect on its card, types a wrong key, Run test; the right key, Run test; Save | Only Key is asked (no header name, no address); 401 then 200; the plugin is on for the team, test Working, the key shown nowhere |
| 16 | Throughout the plugin stack | No page errors |
| 17 | After it | No container of the run is left |
| 14 | Open Bank API's page; Edit keys on Test; type the wrong key, Run test; the right key, Run test; Save | The row shows Working; the key reads Sealed; 401 then 200; the page shows Working |
| 7 | A stack with the switch off: open Connections | The shipped page (Guided connect); no `GET /v1/systems` |

Step 9 checks the dialog's one reducer: when a section's save freed the dialog before its test answered, the walk
read the earlier 401. Step 14 checks that the form stays mounted: when the dialog's own save refetched the connection
and remounted the form, each test showed the one before it. Still to come: reconnect, Salesforce's own app per
environment against `docs/usecases/lib/fake_salesforce.py`, and the run with the switch off reading the sample data.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-580-ui.mjs` | draft |
