# A tool signs in with an API key from its connection, by environment

Status: passing. Id: `uc-390`. Service: `tools-service`. Layers: api, ui. Card: an earlier change.

A connection holds how the platform signs in to one system, with a test value and a production value. A module that
points at it carries no key: the gateway's API key strategy adds the key in a header or the query for the call's
environment. Live runs send `production`; everything else sends `test`, and a call that names none is test. Each
environment names the system's address (`baseUrl`); the key goes to that scheme, host and port only, and a module on
any other address is refused `CONNECTION_HOST_MISMATCH` (`services/tools-service/tests/test_connection_binding.py`).

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A tool on a connection holding a test and a production key sends the key for the call's environment, and test when none is named | api | 1-2 | 2 |
| S2 | A key sent in the query works in test, and a live call with no production key is refused, never sent bare | api | 3 | 3 |
| S3 | No key appears in the call log | api | 4 | 4 |
| S4 | An admin presses Test the team account on a connection's page and it works in production; no key shows on the page | ui | 5 | 5 |
| S5 | Test the team account on a wrong key says Failed with the system's 401 | ui | 6-7 | 7 |

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
| 2 | Create a connection with a test and a production key in `X-Api-Key`; point a module at it | The connection says both keys are set and shows neither; the operation has no key header |
| 2 | Call it in test, in production, and naming no environment | The bank sees the test key, the production key, the test key |
| 3 | A second connection sends the key in the query, test only | A test call carries it in the query; a production call is refused `CONNECTION_NOT_SET` and sent nowhere |
| 4 | Read the call log | No key appears in it |
| 5 | In the console as an Operations admin, open the header connection's page and press Test the team account | Working, 200, production; neither key on the page |
| 6 | The same on the query connection, set for test only | Working, 200, test |
| 7 | The same on a connection whose production key is wrong | Failed, 401 |

The console's connect dialog runs on the mock only, so the ui layer sets its connections up through the API and
tests them on the connection page (shown with the `NEXT_PUBLIC_OPS_PERSONAL_SIGNIN` switch on).

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-390-api.py` | passing, `ISOLATED=1 make usecase-test UC=uc-390 LAYER=api` (2026-10-19) |
| ui | `tools-service/scripts/test-uc-390-ui.mjs` | passing |

## Non-vacuous check

Step 2: with the API key strategy replaced by none, the bank answers 401 to every connection call.
