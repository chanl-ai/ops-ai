# An admin tests a company provider before anyone signs in through it

Status: current. Id: `uc-713`. Service: `platform-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Free use-case ports | the runner picks free ports and its own database |

The script starts platform-service in dev on the run's database with the dev seed (Wanjiru Kamau, the workspace admin)
and the local fake identity provider. No real identity provider and no model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Wanjiru saves a SAML provider, turned off, that makes new people and maps `platform-readers` to team_platform | 200 |
| 2 | Wanjiru starts a test sign-in and signs in at the provider as a new person carrying `platform-readers` | The browser lands on `/settings/security/sign-in?test=<flowId>` |
| 3 | Wanjiru reads the test's result | `ok`, with the email and the groups the provider sent |
| 4 | That person tries to sign in for real | Refused: the provider is still off, and the test made nobody |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-713-api.py` | passing |

In the console: the wizard's Test sign-in step is in progress; this use case stays at the api layer until it ships.

## Non-vacuous check

`the test made nobody`: with test flows sent through the normal answer, the person is made and linked, and step 4
signs in, so the check fails.
