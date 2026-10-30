# A tool signs in with a bearer token from its connection, by environment

Status: passing. Id: `uc-392`. Service: `tools-service`. Layers: api, ui. Card: an earlier change.

The bearer strategy sends `Authorization: Bearer` with the environment's token. Replacing the token reaches the next
call. The token's secret rows are listed on the Secrets page as the connection's and cannot be rotated or removed
there.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A tool sends the test token in test and the production token in production | api | 1 | 1 |
| S2 | A replaced token reaches the next call, and one the system does not know fails with its 401 | api | 2 | 2 |
| S3 | The Secrets list shows the connection's parts with no value and will not rotate them | api | 3 | 3 |
| S4 | An admin presses Test the team account on the connection's page and it works in production; no token shows | ui | 4 | 4 |
| S5 | Test the team account with a token the system does not know says Failed with its 401 | ui | 5 | 5 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The bank stand-in | `core_bank()`; `GET /auth/bearer` answers which token arrived |
| agents-service | `agents()` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Call in test and in production | The bank sees the test token, then the production token |
| 2 | Replace the test token with one the bank does not know, call again | The call fails with the bank's 401 |
| 3 | Read the Secrets list; rotate one of the connection's secrets there | Both parts are listed with the connection's id and no value; 409 `connection_secret` |
| 4 | In the console as an Operations admin, open the connection's page and press Test the team account | Working, 200, production; neither token on the page |
| 5 | The same on a connection whose production token the bank does not know | Failed, 401 |

The console's connect dialog runs on the mock only, so the ui layer sets its connections up through the API and
tests them on the connection page (shown with the `NEXT_PUBLIC_OPS_PERSONAL_SIGNIN` switch on).

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-392-api.py` | passing, `ISOLATED=1 make usecase-test UC=uc-392 LAYER=api` (2026-10-19) |
| ui | `tools-service/scripts/test-uc-392-ui.mjs` | passing |

## Non-vacuous check

Step 1: with the bearer strategy replaced by none, both calls fail 401.
