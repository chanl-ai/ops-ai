# A team admin connects every system for real, from one grid

Status: superseded by uc-607. Id: `uc-580`. Service: `console`. Layers: ui.

Retired 2026-11-01: its pages are gone (one Connect window, the app's page). What only it proved moved: a custom app's
key refused then working and edited from Settings, the certificate app and its thumbprint, Salesforce's own app per
environment, and Reconnect, to uc-607 steps 14-21 (`docs/usecases/console/connect-apps.md`). The grid, the sending
policy and the mock answers are covered by uc-607, uc-266 and uc-397. Its script is removed, so
nothing runs it; this page stays for the record.

Connections in the console showed sample data, so an admin could look at systems but not connect one. Connections is
now a grid of the team's real systems, read from tools-service's
`GET /v1/systems` through the generated SDK (`apps/console/src/lib/api/ops-sdk.ts`). Each card is one system: a
plugin, a connection with the modules that use it, or a module with no connection yet. The API joins each card, so the
console never joins lists itself.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | An admin opens Connections and sees the team's systems as cards, each with its category, line and how it signs in (each environment's state is on the app's page) | ui | 1-2 | 2 |
| S2 | Nothing of another team's reaches the grid | ui | 3 | 3 |
| S3 | Search and the category filter find a system, and the grid fits a phone | ui | 4-5 | 5 |
| S5 | An admin connects a new system from one dialog: a wrong key says Failed with the system's 401, the right one Working, and Save keeps it with the key sealed | ui | 8-10 | 10 |
| S6 | A system whose test fails and is cancelled leaves nothing behind | ui | 11 | 11 |
| S7 | A tool module connected from its card becomes one card with its connection | ui | 12 | 12 |
| S8 | On a connection's page, each environment shows its last test, and Edit keys changes a key the next test reads | ui | 14 | 14 |
| S9 | A plugin connects from its card with only what it needs: a key, never the header the plugin fixes | ui | 15 | 15 |
| S10 | A team admin writes the sending policy where Check before sending is turned on, and each save is a version | ui | 18 | 18 |
| S11 | An operation's mock answers are a list with a default, and a run against the mock gets the one that matches | ui | 19 | 19 |
| S12 | A client-credentials plugin turns on from the dialog with its client ID and secret, never asked for the addresses or permissions it fixes, and a refused test says why in plain words | ui | 20-21 | 21 |
| S13 | On the platform's app, Connect in the small window turns on and signs in for production, and Cancel removes the connection a started sign-in made | ui | 22-23 | 23 |
| S14 | With the team's own app, Save after a section's sign-in closes with no second sign-in window | ui | 24 | 24 |
| S15 | A certificate-signed Entra app connects with its certificate pasted on many lines and its key read from a file, and its page shows the thumbprint and expiry, never the key | ui | 25-27 | 26 |
| S16 | Salesforce's own app per environment: the sandbox and production each sign in to their own org with their own app and land on their own instance | ui | 28 | 28 |
| S17 | When the system refuses the team's refresh, the connection's page asks to Reconnect the team account, and signing in again makes it work | ui | 29 | 29 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| For step 15: plugins on with the header-key test plugin, and the fake system | `tools: { env: { ...fake.settings, OPS_PLUGINS: 'true', OPS_PLUGIN_PATHS } }` |
| The ui stack with platform sign-in and the bank stand-in | `withUiStack(..., { platform: true, tools: { bank: 'core' } })`; `allowBank` lists its host |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | Priya (Operations admin) creates Claims core (Core insurance) and Ledger (Finance); Sam creates Vault for Security | Three connections, 201 each |
| 1 | Priya opens Connections | A grid; the Claims core card shows its name, category, line and how it signs in (API key) |
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
| 20 | In the plugin stack, the client-credentials test plugin: Connect; type client ID `multi-cc` and a wrong secret, Run test; the right secret, Run test; Save | Only Client ID and Client secret are asked (no Token address, no permissions); Working; on for the team |
| 21 | The wrong secret's result | Failed, said in plain words with no raw code such as AUTH_FAILED |
| 22 | The person desk plugin, the platform's app set up by Sam: Connect opens the small window; Connect; Cancel while the sign-in window is open | The window closes; the connection the sign-in made is deleted (404) and the plugin is off |
| 23 | Connect again; Connect; sign in in the window | The sign-in is for Production; the app's page opens once the test works; Production Working, Test not set |
| 24 | Remove it and the platform's app secret, so Connect opens the full dialog; Connect with Our own app on Test; Sign in and test; Save | One sign-in window in all; the dialog closes; Test Working |
| 25 | A stack with the Entra test plugin and the fake token endpoint (`docs/usecases/lib/fake_token_endpoint.py`): Connect; client ID, How the client is sent `private_key_jwt`, the certificate pasted, the key read from a file; Run test; Save | The certificate box is multi-line; Working; on for the team |
| 26 | Open its connection page | Signing certificate, its thumbprint and expiry on Production; no private key in the page |
| 27 | Throughout the Entra stack | No page errors |
| 28 | A stack with the Salesforce plugin (ops-ai-plugins) and the fake Salesforce with its sandbox org: Connect; Our own app; Test: a sandbox app, its secret and the sandbox sign-in address, Sign in and test; Production: the production app and address, Sign in and test; Save | Two sign-in windows in all; both Working; the test environment's address is the sandbox instance, production's the production instance; the fake saw both apps |
| 29 | The fake refuses the next call and every refresh; Run test on Production; reload; Reconnect the team account; sign in; Run test | The page asks to Reconnect the team account; after it, the connection is healthy and Production Working |
| 30 | Throughout the Salesforce stack | No page errors |

Step 9 checks the dialog's one reducer: when a section's save freed the dialog before its test answered, the walk
read the earlier 401. Step 14 checks that the form stays mounted: when the dialog's own save refetched the connection
and remounted the form, each test showed the one before it. Steps 20 to 27 are the 10-30 PM test's broken plugin sign-ins. Step 7 and story S4 (the page with the switch off) were
removed on 10-31 with the switch: a shipped feature has no switch.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-580-ui.mjs` | draft |
