# Connect comes back Connected in any window, for every sign-in app

Status: draft. Id: `uc-625`. Service: `tools-service`. Layers: ui.

A person presses Connect, allows access on the system's own page, and the system sends them back to the console's
return page with only a code and a state. The return page hands both to `POST /v1/sign-ins/complete`, which finds the
sign-in from its state alone, so the page needs nothing kept in the browser. The window that pressed Connect learns
the outcome by message, by broadcast, or by reading the account, closes the sign-in window and shows Connected.

The walk runs on its own stack against fakes of each system, so no real provider is reached: the plugins repo's
`plugins/github/tests/fake_github.py` for GitHub, `docs/usecases/lib/fake_salesforce.py` for Salesforce and
`docs/usecases/lib/fake_multi_auth.py` for the tests' Person desk (`services/tools-service/tests/plugin_kinds`).
Ticket desk signs in with an API key, so it has no return page and is not walked here.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A sign-in window left open from before is never reused: Connect opens one of its own | ui | 11, 21, 31 | 11 |
| S2 | A refused sign-in says, in one sentence in both windows, who acts next | ui | 12, 22, 32 | 12 |
| S3 | A sign-in window closed early says "The window was closed", and Try again connects; the app's page reads Connected | ui | 13-14, 23-24, 33-34 | 13 |
| S4 | A sign-in finished in a fresh browser with no storage still reads Connected in the window that started it | ui | 15, 25, 35 | 15 |
| S5 | Connect and Add account ask where a Salesforce account signs in, with the plugin's choices, starting from the first account's address | ui | 26, 28 | 26 |
| S6 | Once connected, the app's header says Connected with the default account's name | ui | 17, 27, 37 | 17 |
| S7 | A team's own auth config shows the callback URL to register in the system's app, with a copy button, on its row and in Edit | ui | 41 | 41 |
| S8 | A member who may not connect is told to ask an admin, by name, on the card and the app page | ui | 51 | 51 |
| S9 | Add account has a Test account switch a test sign-in place turns on, and no screen says sandbox | ui | 52 | 52 |
| S10 | An app's Settings show its API and sign-in addresses and call out a test host | ui | 53 | 53 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Docker, for the mock OAuth server the Salesforce and multi-auth fakes run | Docker running |
| The plugins repo beside this one | `../ops-ai-plugins`, for the GitHub and Salesforce plugins and the fake GitHub |

## Steps and expected results

Steps run once per app, numbered by app and step: 11-15 GitHub, 21-25 Salesforce, 31-35 Person desk.

| # | Step | Expected |
|---|---|---|
| 0 | List the apps | The three apps are listed with Ops AI's own app |
| n1 | Open a window named `ops-sign-in`, then Connect | A new sign-in window opens on the system's page; the old window keeps its address |
| n2 | Refuse on the system's page | The Connect window and the sign-in window both show the plugin's sentence, which says who acts |
| n3 | Connect, then close the sign-in window on the system's page | The Connect window says "The window was closed" and its button reads Try again |
| n4 | Try again, allow | A new window opens, closes once allowed, and the app's page and `GET /v1/apps` read Connected |
| n5 | Add account, then open the system's page in a fresh browser signed in as the same person and allow there | The fresh browser shows the account connected; the first window closes its sign-in window and its Connect window, and the account reads connected |
| n6 | (Salesforce) Open Connect | Where do you sign in is asked outside More options, with login.salesforce.com, test.salesforce.com and your company's address |
| n7 | After n4 | The header reads "Connected · " and the default account's name |
| n8 | (Salesforce) Add account | Where it signs in starts at the first account's company address |
| 41 | Make a team auth config for GitHub, open the app page and Edit | The row and Edit show `<console>/connections/sign-in/return`, with a copy button |
| 51 | The viewer opens Apps and GitHub's page before anyone connects it | Both say "Ask an admin" and name Priya Shah |
| 52 | Add account on Salesforce, pick test.salesforce.com | The Test account switch turns on; the page and window never say sandbox |
| 53 | GitHub's Settings tab | Its API and sign-in addresses, each on a `.test` host marked Test host |
| 9 | Every page | No page errors |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `tools-service/scripts/test-uc-625-ui.mjs` | written |

## Non-vacuous check

Step 13: with no `onClosed` handler in the Connect window, a sign-in window closed early left it on "Connecting…"
and the step failed. Step 15 fails when the opener only listens for messages, since a fresh browser shares neither
a window nor a broadcast channel with it.
