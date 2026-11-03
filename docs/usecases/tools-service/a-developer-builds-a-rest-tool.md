# A developer builds a REST tool and runs it for real

Status: current. Id: `uc-611`. Service: `tools-service`. Layers: api, sdk, ui.

James, a developer in Operations, connects a payments system the way an API client does: he opens a REST tool,
runs it in Mock before anything is set up, picks the connection that holds the system's key, and runs a form-encoded
write and a search for real. The payments system is the fake bank's Stripe-shaped stand-in, which takes a customer
only as a form body behind a Bearer key.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | James runs a new tool in Mock before it has a connection, sees the mock answer, and sees Real can be chosen once the tool is published | ui | 1-3 | 3 |
| S2 | James picks the payments connection and runs the write for real: the customer is made, the answer is badged Real, and Request sent shows the form body with the key hidden | ui | 4-6 | 6 |
| S3 | James searches by email with `{email}` in the address and finds that customer for real | ui | 7 | 7 |
| S4 | James saves a key in the Authorization header and a Content-Type the body sets, and one message lists both problems | ui | 8 | 8 |
| S5 | The real write is in the executions log under James, and someone outside Operations cannot run it for real | api | 9-10 | 10 |
| S6 | A tool addressed by its path alone runs against the app's base address, and a module naming its own base address is refused | api | 11-12 | 11 |
| S7 | A sign-in key in an operation's header is refused, typed or referenced, because the app signs every call | api | 13 | 13 |
| S9 | In the console a tool's address comes from its app, and New module names the app it calls with no type | ui | 15 | 15 |
| S10 | A tool saved before sign-in headers were refused says to move its key to the app; a clean tool says nothing | ui | 16 | 16 |
| S11 | A refused run's Request sent says why nothing went out | ui | 17 | 17 |
| S8 | Through the Python SDK a builder adds a custom REST app with its base address and key, and a tool addressed by its path runs Real with both | sdk | 14 | 14 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The fake bank on https, its host on the egress list | the harness's `tools: { bank: 'core' }` stack; `allowBank` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James's published module has `create_customer` (POST, form body `email={{email}}`, `metadata[source]=ops_ai`) and `search_customers` (GET `?email={email}`), with no connection; a Bearer connection, made by Priya (Admin in Operations), holds the bank's test key | set up through the API |
| 2 | James opens `create_customer` | Real can be chosen, since the tool is published |
| 3 | He types an email and presses Run in Mock | the answer is badged Mock, and Request sent says nothing was sent |
| 4 | He picks the payments connection on the page | the field says the connection signs every Real request in to the bank |
| 5 | He runs it in Real | HTTP 200, a `cus_` id, the answer badged Real |
| 6 | He opens Request sent | `application/x-www-form-urlencoded`, `email=` with his address, the Authorization value hidden, the key nowhere on the page |
| 7 | He opens `search_customers` and runs it in Real with the same email | the answer lists the customer made in step 5 |
| 8 | On `create_customer` he adds `Authorization: Bearer sk_live_…` and `Content-Type: application/json` and presses Save | one message, "Couldn’t save: 2 problems", naming the connection and the encoding; his edits stay |
| 9 | The executions log is read for `create_customer` | one row, channel `console`, environment `test` |
| 10 | Someone in Cards asks for a Real run of `create_customer` | refused, and nothing more is written |
| 11 | James makes a module bound to the payments connection whose operation's address is the path `/auth/bearer/customers/search?email={email}` and runs it Real | 201; the answer lists the customer from step 5, read with the connection's key from its base address |
| 12 | He makes a module naming its own base address (`endpoint`) beside the connection | 400 or 422 |
| 13 | He saves `Authorization: Bearer sk_test_literal`, then `Authorization: Bearer {{PAYMENTS_KEY}}`, on `create_customer` | Both 400; the second names the connection |
| 14 | (sdk, on the Apps stack) James adds a custom REST app (`ops.apps.add_custom` with the fake's base address and token), a tool `/bearer/records/{id}`, and runs it Real (`ops.tools.run`) | The record comes back; the fake received the app's token; the token in no answer |
| 15 | On the tool page the connection field reads App and the address starts with the app's base address; James presses New module, names it, picks the payments app and saves | The request carries `connectionId` and no `type`; the module's connection is the app, and its page shows the app's base address |
| 16 | A tool whose saved headers still carry `X-Api-Key` (written into the run's database, as a tool saved before the refusal was left) is opened, then a clean tool | The first shows "This tool sends a sign-in header; move it to the app" naming X-Api-Key, and the module answer's `signInHeader` is X-Api-Key; the clean tool shows nothing |
| 17 | A run the gateway refuses before sending (answered as a refusal in the browser) | Request sent says nothing was sent because the call was refused, with the reason; it never says a mock answered |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `tools-service/scripts/test-uc-611-ui.mjs` | written |
| api | `tools-service/scripts/test-uc-611-api.py` | written; 11-13 target: wait on S4 and D3 |
| sdk | `tools-service/scripts/test-uc-611-sdk.py` | target: waits on P1, S4 and K1 |

## Non-vacuous check

Step 5 fails with Real answering writes from the stub (the rule before an earlier change), and step 8 fails when a save reports only
its first problem; both were seen failing in tools-service's tests (`tests/test_test_console_reads.py`,
`tests/test_body_encoding.py`).
