# A tool signs in with a bearer token from its connection, by environment

Status: passing. Id: `uc-392`. Service: `tools-service`. Layers: api. Card: c-330.

The bearer strategy sends `Authorization: Bearer` with the environment's token. Replacing the token reaches the next
call. The token's secret rows are listed on the Secrets page as the connection's and cannot be rotated or removed
there.

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

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-392-api.py` | passing, `ISOLATED=1 make usecase-test UC=uc-392 LAYER=api` (2026-10-19) |

## Non-vacuous check

Step 1: with the bearer strategy replaced by none, both calls fail 401.
