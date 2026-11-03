# A team connects apps from one catalog

Status: draft. Id: `uc-607`. Service: `console`. Layers: api, sdk, cli, ui.

Connections was a grid of systems and one large dialog, so connecting an app took many fields and a person could not
see whether they were signed in. Connections is now a catalog of apps: a plugin connects in one
Connect window, and each app has its own page with its accounts, the person's own sign-in, and tabs for
Tools, Skills, Sign-in and secrets, Usage and Settings. The catalog reads `GET /v1/systems` and the page reads
`GET /v1/apps/{id}`, each already joined, so the console never joins lists itself.

The walk runs on its own stack with the test plugins of `services/tools-service/tests/plugin_kinds` and the fake
system of `docs/usecases/lib/fake_multi_auth.py`, which signs in any account name it is given. The install turns on
`several_accounts` for steps 11-13; `docs/usecases/lib/agents_call.py` makes step 12's calls as agents-service does.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A team member opens Connections and sees each app once as a card, plugins first, with its tools, how it signs in and Connect, read in one call; search finds an app | ui | 1-2 | 2 |
| S2 | An admin presses Connect on an app, allows access on the system's page, and lands on the app's page with the team's account listed as the default | ui | 3-4 | 4 |
| S15 | A test call that fails after the sign-in leaves the account Connected and shows the reason on its row and the catalog card, with Reconnect | ui | 29 | 29 |
| S16 | Settings › Edit keeps what was saved: its fields start blank, and saving without typing changes nothing; the sign-in address typed on the first Connect is the one used | ui | 19, 30 | 30 |
| S14 | One Connect window: Ops AI's app or the team's own, the access asked for, then Authorize; the sign-in window opens at once; a refused sign-in shows in both windows and Authorize works again; an app turned on again continues with its app credential | ui | 3 | 3 |
| S3 | A person presses Connect my account, allows access, and the page reads Connected as their account; a tool the agent then calls runs with it, shown on Usage | ui | 5-7 | 7 |
| S4 | Ops AI's own tools show as Built in apps that open the page managing them | ui | 8 | 8 |
| S5 | The app's tabs show its tools by title, its sign-ins with no secret, and its Settings with the one sign-in switch and each environment | ui | 9 | 9 |
| S6 | With several_accounts on, an admin connects another account of the app under its own name; both are listed and the first stays the default | ui | 11 | 11 |
| S7 | A call naming an account runs with it, a call naming none with the default, and an unknown name is refused | ui | 12 | 12 |
| S8 | A person signed in to two accounts reads with their newest, and Make my default picks the other | ui | 13 | 13 |
| S9 | Add custom app: a refused key says Failed with the app's 401, the right one Working with 200, and the key is sealed (from uc-580) | ui | 14 | 14 |
| S10 | An app's Settings show each environment's last test; Edit opens the Connect window on it with the key sealed (from uc-580) | ui | 15 | 15 |
| S11 | A certificate app connects in the window, and its Settings show the certificate's thumbprint and expiry, never its key (from uc-580) | ui | 17 | 17 |
| S12 | Salesforce's own app per environment: production in the window, the sandbox from Settings › Set up test, each on its own instance (from uc-580) | ui | 19 | 19 |
| S13 | When the app refuses the team account's refresh, the account reads Expired with Reconnect, and signing in again makes it work (from uc-580) | ui | 21 | 21 |
| S9 | Anyone in the team lists the apps in one call: the plugins and the apps a person added, no built-in app and no connection made for a tool; an app turned on with a key reads Connected only once a test has passed | api | 20-21, 28 | 21 |
| S10 | A viewer sees the apps but may not turn one on, while the admin may; the app's page reads Connected · team account | api | 22-23 | 23 |
| S11 | A developer lists the connected apps and reads one through the Python SDK and gets what the API gives | sdk | 24 | 24 |
| S12 | A team admin lists and shows apps with `ops apps`; a viewer's `ops apps connect` is refused | cli | 25-26 | 25 |

## Steps

| # | Step | Expect |
|---|---|---|
| 0 | Set-up through the API: the install turns on Person desk with Ops AI's own app (client id and sealed secret), the fake's hosts are allowed, and an agent holds Person desk's read tool | each call 2xx |
| 1 | Priya opens Connections | a card for Person desk with 1 tool, Plugin and Connect; the page read `GET /v1/systems` and no other list |
| 2 | She searches "person" | the count reads 1 of N and only Person desk shows |
| 3 | She presses Connect on Person desk, then Authorize with Person desk, and the system sends her back refused (error=access_denied) | the window offers Ops AI's app and Your own app, the access asked for, and More options folded; the sign-in window opens on /connections/connect?app=Person desk; it reads Access was not given with Close, and the Connect window shows the refusal with Authorize enabled |
| 4 | She opens More options, names the account Person desk, presses Authorize and allows access as harbor.ops in the system's window | the window closes, the app's page reads Connected, and Accounts lists Person desk as Default |
| 5 | James opens the app's page | Connect my account |
| 6 | He presses it and allows access as james.person | the page reads Connected as james.person |
| 7 | He asks the agent in chat for a record, then opens Usage | the chat answers with the record read as james.person; Usage lists Read a record by James, Succeeded |
| 8 | Priya opens Connections | each Built in card present opens its managing page (Knowledge bases at /knowledge, Mailboxes at /channels/email) |
| 9 | Priya opens Tools, Sign-in and secrets and Settings | Read a record with its name; the team account's sign-in with no secret on the page; the switch and both environments |
| 11 | Priya presses Connect another account, which opens the Connect window with its name showing, names it EU desk, presses Authorize and allows access as harbor.eu | Accounts lists Person desk (Default) and EU desk |
| 12 | A run with nobody behind it calls Read a record naming EU desk, then naming nothing, then naming Nowhere desk | The system reads as harbor.eu, then harbor.ops; the third is refused 404 ACCOUNT_NOT_FOUND |
| 13 | James connects his own EU desk account (james.eu) and asks the agent for a record; then presses Make my default on Person desk and asks again | The first read is as james.eu, his newest sign-in; the second as james.person |
| 14 | On a stack with the bank stand-in, Priya presses Add custom app, names it Bank API, types the address, test path and a wrong key, presses Test, then the right key and Test, then Save | Failed with 401, then Working with 200; the key reads Sealed |
| 15 | She opens Bank API's Settings, presses Edit on Production, types a wrong key and tests, the right one and tests, saves, and presses Test | Production Working; the window shows the key sealed; 401, then 200; Working after |
| 17 | On a stack with the certificate test app and the fake token endpoint, she connects it in the window with its certificate pasted and its key from a file, tests and saves, then opens its Settings | The test works; Signing certificate with its thumbprint and expiry; no private key on the page |
| 19 | On a stack with the fake Salesforce, she connects Salesforce with her own app for Production and signs in, then Settings › Set up test with the sandbox app and signs in | Both environments Working; each on its own instance |
| 21 | The fake refuses the next call and the refresh; she tests Production, reloads, presses Reconnect on the expired account and signs in again | The account reads Expired with Reconnect; after signing in, the app is healthy and Production Working |
| 20 | Priya lists `GET /v1/systems` | 200; the test plugins, and no built-in app (each has its own menu) |
| 21 | Priya turns the header-key desk on with its key (`PUT /v1/plugins/test.header-key/team`), reads its card, tests the team account, reads it again | Not connected before the test; status connected after it |
| 22 | Ravi (viewer) lists `GET /v1/apps` and turns the query-key desk on | The list 200; the turn-on 403 |
| 23 | Priya reads `GET /v1/apps/plugin:test.header-key` | Its accounts list the team account first, default, state connected |
| 24 | Priya, through the SDK, calls `ops.apps.list(connected=True)` and `ops.apps.get` | The app among only connected cards; its name |
| 25 | Priya runs `ops apps list --connected` and `ops apps show plugin:test.header-key` | Exit 0; the list holds the app; show names it |
| 26 | Ravi runs `ops apps connect plugin:test.query-key` | A non-zero exit naming the refusal (403) |
| 27 | The console steps for group A (Apps grid, Connected only and Available only, the small Connect window) | Written by the console builder with tasks U1-U3; steps 1-13 stay until then |
| 29 | Security takes Person desk's hosts off the allow list and the team account is tested; then the hosts go back and it is tested again | the account row and the catalog card read "Signed in, but a test call failed" with Reconnect; after, the account is Connected and the test passes |
| 30 | On Salesforce's Settings, Priya presses Edit on Production and Save without typing | the sign-in address field is blank with "Blank keeps the saved value."; the saved settings are unchanged |
| 28 | Priya makes a tool from a full URL (`POST /v1/tool-modules`), lists `GET /v1/systems`, and reads the tool's connection page and `builtin:files` | The tool's own connection, the built-in apps and module cards are not listed; both pages answer 200 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `console/scripts/test-uc-607-api.py` | target: 21 and 23 wait on S1 and D2 |
| sdk | `console/scripts/test-uc-607-sdk.py` | target: waits on K1 |
| cli | `console/scripts/test-uc-607-cli.py` | target: waits on L1 |
| ui | `console/scripts/test-uc-607-ui.mjs` | draft (steps 1-13) |

## Non-vacuous check

Step 21: the app is not in `?only=connected` before its test passes. Today a saved key alone reads as connected, so the
check fails until S1 lands. Step 22 pairs the viewer's 403 with the admin's turn-on in step 21.

Screenshots of each screen at 1280 in light and dark go to `evidenceDir('607', 'uc')`, beside the mock's frames.
