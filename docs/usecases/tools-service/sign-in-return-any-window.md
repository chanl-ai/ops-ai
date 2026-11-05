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
| S1 | A sign-in window left open from before is never reused: Connect opens one of its own | ui | 1.1, 2.1, 3.1 | 1.1 |
| S2 | A refused sign-in says, in one sentence in both windows, who acts next | ui | 1.2, 2.2, 3.2 | 1.2 |
| S3 | A sign-in window closed early says "The window was closed", and Try again connects; the app's page reads Connected | ui | 1.3-1.4, 2.3-2.4, 3.3-3.4 | 1.3 |
| S4 | A sign-in finished in a fresh browser with no storage still reads Connected in the window that started it | ui | 1.5, 2.5, 3.5 | 1.5 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Docker, for the mock OAuth server the Salesforce and multi-auth fakes run | Docker running |
| The plugins repo beside this one | `../ops-ai-plugins`, for the GitHub and Salesforce plugins and the fake GitHub |

## Steps and expected results

Steps run once per app: 1 is GitHub, 2 Salesforce, 3 Person desk.

| # | Step | Expected |
|---|---|---|
| 0 | List the apps | The three apps are listed with Ops AI's own app |
| n.1 | Open a window named `ops-sign-in`, then Connect | A new sign-in window opens on the system's page; the old window keeps its address |
| n.2 | Refuse on the system's page | The Connect window and the sign-in window both show the plugin's sentence, which says who acts |
| n.3 | Connect, then close the sign-in window on the system's page | The Connect window says "The window was closed" and its button reads Try again |
| n.4 | Try again, allow | A new window opens, closes once allowed, and the app's page and `GET /v1/apps` read Connected |
| n.5 | Add account, then open the system's page in a fresh browser signed in as the same person and allow there | The fresh browser shows the account connected; the first window closes its sign-in window and its Connect window, and the account reads connected |
| 9 | Every page | No page errors |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `tools-service/scripts/test-uc-625-ui.mjs` | written |

## Non-vacuous check

Step 1.3: with no `onClosed` handler in the Connect window, a sign-in window closed early left it on "Connecting…"
and the step failed. Step 1.5 fails when the opener only listens for messages, since a fresh browser shares neither
a window nor a broadcast channel with it.
