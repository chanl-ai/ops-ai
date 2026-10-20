# A tool signs in with a username and password from its connection, by environment

Status: passing. Id: `uc-391`. Service: `tools-service`. Layers: api. Card: c-330.

The basic strategy sends `Authorization: Basic` with the connection's username for the environment and its password,
a secret part written once and never shown. A change against a revision someone else already changed is refused.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The bank stand-in | `core_bank()`; `GET /auth/basic` answers which user signed in |
| agents-service | `agents()` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Set test (`ops-test`) and production (`ops-prod`) users with passwords | The username shows; the password is set and never shown |
| 2 | Call in test and in production | The bank sees `ops-test`, then `ops-prod` |
| 3 | Change the test settings against the first revision; send the password as a plain setting | 409 `stale_version`; 400 |
| 4 | Read the call log | Each row names its environment and the connection; no password appears |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-391-api.py` | passing, `ISOLATED=1 make usecase-test UC=uc-391 LAYER=api` (2026-10-19) |

## Non-vacuous check

Step 2: with the basic strategy replaced by none, both calls fail 401 (`.codeloop/evidence/330/uc-391-red-without-strategy.txt`).
