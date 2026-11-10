# A chat uses the account picked for it, and a new chat starts on the default

Status: current on main behind the `OPS_PLUGINS` switch. Id: `uc-697`. Service: `agents-service` with tools-service,
platform-service and the console. Layers: ui. Guide: `docs/guide/plugins.md`, Several accounts of one app. Design: the
several accounts per app design, AC3.

The design draws this with a person's two own GitHub sign-ins and a pinned default. This use case uses two team accounts
of Salesforce instead, with the team's default standing for the default: an own sign-in needs a browser OAuth flow per
person on a second fake, while the team accounts sign in through the fake Salesforce the other several-accounts use
cases already run. The person's own default is proved at the api layer by uc-702.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A new chat's connectors picker says the app uses the team's default account | ui | 1 | 1 |
| S2 | A person changes the chat's account in the picker and the chat's next query runs in that account | ui | 2, 3 | 2 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| Plugins | The `ops-ai-plugins` repository beside ops-ai, or `OPS_PLUGINS_REPO` |
| Fake Salesforce | `docs/usecases/lib/fake_salesforce.py` (production and EU orgs) |
| People | Priya Shah (team admin) sets up; Maya Okafor chats; password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | Priya turns Salesforce on as Retail org, adds EU org at the EU My Domain, signs both in, and gives agent "Case desk" `salesforce_query` | Both accounts are connected; Retail org is the team default |
| 1 | Maya opens a new chat with Case desk and opens the connectors picker | Salesforce reads "Uses Retail org" |
| 2 | She sends a first message, picks EU org under Change, and writes `call salesforce_query {...}` | The fake answers the query on `kestrel-eu.my.salesforce.test` only |
| 3 | `GET /chat/threads/{id}/connectors` as Maya | Salesforce's row has `account` EU org |

Steps 1 to 3 run at 1440 and 390 wide, with screenshots in the evidence folder (`OPS_USECASE_SHOTS`).

## What would make a step pass with the code broken

| Step | Guard against a vacuous pass |
|---|---|
| 2 | With `PUT /chat/threads/{id}/connectors` (`api/routers/chat_connectors.py` set_connectors) dropping `accounts`, the query reaches the production org and step 2 fails |
| 3 | The same revert leaves the chat with no account, and step 3 fails |

## Scripts

| Layer | Script |
|---|---|
| ui | `docs/usecases/agents-service/scripts/test-uc-697-ui.mjs` |
