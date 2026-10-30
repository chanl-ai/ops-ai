# A tool signs in with a username and password from its connection, by environment

Status: passing. Id: `uc-391`. Service: `tools-service`. Layers: api, ui. Card: an earlier change.

The basic strategy sends `Authorization: Basic` with the connection's username for the environment and its password,
a secret part written once and never shown. A change against a revision someone else already changed is refused.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A tool signs in as the test user in test and the production user in production, and the password is never shown | api | 1-2 | 2 |
| S2 | A stale change is refused, and a password sent as a plain setting is refused | api | 3 | 3 |
| S3 | The call log names each call's environment and connection, and no password | api | 4 | 4 |
| S4 | An admin presses Test the team account on the connection's page and it works in production; no password shows | ui | 5 | 5 |
| S5 | Test the team account with a wrong password says Failed with the system's 401 | ui | 6 | 6 |

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
| 5 | In the console as an Operations admin, open the connection's page and press Test the team account | Working, 200, production; neither password on the page |
| 6 | The same on a connection whose production password is wrong | Failed, 401 |

The console's connect dialog runs on the mock only, so the ui layer sets its connections up through the API and
tests them on the connection page (shown with the `NEXT_PUBLIC_OPS_PERSONAL_SIGNIN` switch on).

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-391-api.py` | passing, `ISOLATED=1 make usecase-test UC=uc-391 LAYER=api` (2026-10-19) |
| ui | `tools-service/scripts/test-uc-391-ui.mjs` | passing |

## Non-vacuous check

Step 2: with the basic strategy replaced by none, both calls fail 401.
