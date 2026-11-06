# A tool signs in with an API key from its app's account, the sandbox's in a test run

Status: passing. Id: `uc-390`. Service: `tools-service`. Layers: api, ui.

An app's account holds how the platform signs in to one system. An app may also have a sandbox account, which test runs
use. A module that points at the app carries no key: the gateway's API key strategy adds the account's key in a header
or the query. Live runs send `production`; everything else sends `test`, and a call that names none is a test run. A
test run uses the sandbox account when the app has one, else the live account; a live run never uses a sandbox
account. Each account names the system's address (`baseUrl`); the key goes to that scheme, host and port only, and a
module on any other address is refused `CONNECTION_HOST_MISMATCH` (`services/tools-service/tests/test_connection_binding.py`).

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A tool on an app with a live and a sandbox account sends the sandbox's key in a test run and the live account's in a live run, and a call naming no run is a test run | api | 1-2 | 2 |
| S2 | A key sent in the query works in a test run, and a live call on an app with only a sandbox account is refused, never sent bare | api | 3 | 3 |
| S3 | No key appears in the call log | api | 4 | 4 |
| S4 | An admin presses Test on an app page's Keys row and its live account works; no key shows on the page | ui | 5-6 | 5 |
| S5 | Test on a wrong key says Failed with the system's 401 | ui | 7 | 7 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The bank stand-in on https as api.bank.test | `core_bank()`; `GET /auth/api-key` answers which key arrived (`services/tools-service/scripts/fake_bank/bank_auth.py`) |
| agents-service, which holds the module's review | `agents()` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Call a module with no connection | The bank refuses it (401) |
| 2 | Create an app with a live account and a sandbox account, each with its own key in `X-Api-Key`; point a module at it | Each account says its key is set and shows neither; the operation has no key header |
| 2 | Call it in a test run, a live run, and naming no run | The bank sees the sandbox key, the live key, the sandbox key |
| 3 | A second app, whose only account is a sandbox, sends the key in the query | A test call carries it in the query; a live call is refused `CONNECTION_NOT_SET` and sent nowhere |
| 4 | Read the call log | No key appears in it |
| 5 | In the console as an Operations admin, open the header key app's page and press Test on Settings › Keys | Working, 200, with the team account; neither key on the page |
| 6 | The same on the query key app, whose only account is a sandbox | Working, 200 |
| 7 | The same on an app whose live key is wrong | Failed, 401 |

The ui layer sets its apps up through the API, as the api layer does, and tests each on its app page.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-390-api.py` | passing, `make usecase-test UC=uc-390 LAYER=api` (2026-10-19) |
| ui | `tools-service/scripts/test-uc-390-ui.mjs` | passing, `make usecase-test UC=uc-390 LAYER=ui` (2026-11-03) |

## Non-vacuous check

Step 2: with the API key strategy replaced by none, the bank answers 401 to every connection call.
