# Wrong passwords lock sign-in and step-up, and reset mail is capped

Status: current. Id: `uc-214`. Service: `platform-service`. Layers: api, ui (ui layer an earlier change).

## Preconditions

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Lena types a wrong password five times; the fifth locks sign-in and the page says so | ui | 1 | 1 |
| S2 | Her right password is refused while the lock holds | ui | 2 | 2 |
| S3 | She resets her password from the mailed link and signs in: the reset ended the lock | ui | 5 | 5 |

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Free use-case ports | the runner picks free ports and its own database |

The script starts platform-service in dev on the run's database with the dev seed (Lena Fischer and Omar Haddad,
fraud approvers), sign-in URLs and reset mail written to a folder. The limits are the defaults: five wrong passwords in
fifteen minutes lock for fifteen, and three reset links an hour. No model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Lena types a wrong password five times | 401 four times, then 429 `signin_locked` |
| 2 | Lena types her right password | 429 `signin_locked` with a `Retry-After` header |
| 3 | Omar signs in, types four wrong passwords at sign-in and one at step-up | The step-up is 429: both count together |
| 4 | Lena asks for a reset link four times | Each answered 204; three mails go out |
| 5 | Lena sets a new password through the last link and signs in with it | 204, then 200: the reset ended the lock |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-214-api.py` | passing |
| ui | `platform-service/scripts/test-uc-214-ui.mjs` | passing: the sign-in page, Forgot password and the reset page |

## Non-vacuous check

With the lock check and the reset cap removed, every lockout test in `services/platform-service/tests/test_signin_lockout.py`
fails.
