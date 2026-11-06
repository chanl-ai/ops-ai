# A tool signs in with a bearer token from its app's account

Status: passing. Id: `uc-392`. Service: `tools-service`. Layers: api, ui.

The bearer strategy sends `Authorization: Bearer` with the account's token: the sandbox account's in a test run, the
live account's in a live run. Replacing the token reaches the next
call. The token's secret rows are listed on the Secrets page as the account's and cannot be rotated or removed
there.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A tool sends the sandbox account's token in a test run and the live account's in a live run | api | 1 | 1 |
| S2 | A replaced token reaches the next call, and one the system does not know fails with its 401 | api | 2 | 2 |
| S3 | The Secrets list shows the connection's parts with no value and will not rotate them | api | 3 | 3 |
| S4 | An admin presses Test on the app page's Keys row and its live account works; no token shows | ui | 4 | 4 |
| S5 | Test with a token the system does not know says Failed with its 401 | ui | 5 | 5 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The bank stand-in | `core_bank()`; `GET /auth/bearer` answers which token arrived |
| agents-service | `agents()` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Call in a test run and in a live run | The bank sees the sandbox token, then the live token |
| 2 | Replace the test token with one the bank does not know, call again | The call fails with the bank's 401 |
| 3 | Read the Secrets list; rotate one of the connection's secrets there | Both parts are listed with the connection's id and no value; 409 `connection_secret` |
| 4 | In the console as an Operations admin, open the app's page and press Test on Settings › Keys | Working, 200, with the team account; neither token on the page |
| 5 | The same on an app whose live token the bank does not know | Failed, 401 |

The ui layer sets its apps up through the API, as the api layer does, and tests each on its app page.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-392-api.py` | passing, `make usecase-test UC=uc-392 LAYER=api` (2026-10-19) |
| ui | `tools-service/scripts/test-uc-392-ui.mjs` | passing, `make usecase-test UC=uc-392 LAYER=ui` (2026-11-03) |

## Non-vacuous check

Step 1: with the bearer strategy replaced by none, both calls fail 401.
