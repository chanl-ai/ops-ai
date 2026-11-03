# A tool signs in with a username and password from its app's account

Status: passing. Id: `uc-391`. Service: `tools-service`. Layers: api, ui.

The basic strategy sends `Authorization: Basic` with the account's username and its password, a secret part written
once and never shown. A test run uses the app's sandbox account, a live run its live account. A change against a revision someone else already changed is refused.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A tool signs in as the sandbox account's user in a test run and the live account's user in a live run, and the password is never shown | api | 1-2 | 2 |
| S2 | A stale change is refused, and a password sent as a plain setting is refused | api | 3 | 3 |
| S3 | The call log names each call's run and the account it signed in with, and no password | api | 4 | 4 |
| S4 | An admin presses Test on the app page's Keys row and its live account works; no password shows | ui | 5 | 5 |
| S5 | Test with a wrong password says Failed with the system's 401 | ui | 6 | 6 |

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
| 2 | Call in a test run and in a live run | The bank sees `ops-test` (the sandbox account), then `ops-prod` (the live account) |
| 3 | Change the test settings against the first revision; send the password as a plain setting | 409 `stale_version`; 400 |
| 4 | Read the call log | Each row names its run and the account it signed in with; no password appears |
| 5 | In the console as an Operations admin, open the app's page and press Test on Settings › Keys | Working, 200, with the team account; neither password on the page |
| 6 | The same on an app whose live password is wrong | Failed, 401 |

The ui layer sets its apps up through the API, as the api layer does, and tests each on its app page.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-391-api.py` | passing, `ISOLATED=1 make usecase-test UC=uc-391 LAYER=api` (2026-10-19) |
| ui | `tools-service/scripts/test-uc-391-ui.mjs` | passing, `make usecase-test UC=uc-391 LAYER=ui` (2026-11-03) |

## Non-vacuous check

Step 2: with the basic strategy replaced by none, both calls fail 401.
