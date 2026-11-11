# Company sign-in required, with a break-glass Security admin

Status: current. Id: `uc-712`. Service: `platform-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Free use-case ports | the runner picks free ports and its own database |

The script starts platform-service in dev on the run's database with the dev seed (Wanjiru Kamau, the workspace admin;
Sam Adeyemi, admin of team_security and so its Security admin; demo password `northfield-demo`) and the local fake
identity provider. No real identity provider and no model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Wanjiru keeps the password provider on and sets a SAML provider for `harborpine.example` | 200, 200 |
| 2 | Wanjiru turns on `companySignInRequired` | 409 `break_glass_none`: nobody could get in if the provider were down |
| 3 | Wanjiru names Sam as a break-glass account, then turns the policy on | 200, 200 |
| 4 | Wanjiru signs in with her password | 401, the same refusal as a wrong password |
| 5 | Sam signs in with his password | 200; audited `signin.break_glass_used` and told to the Security admins |
| 6 | Wanjiru takes Sam off the list | 409 `break_glass_last` |

The service tests (`services/platform-service/tests/test_saml_break_glass.py`) also cover: only a Security admin can be
on the list, the usual lockout applies to break-glass accounts, the only provider of a verified domain cannot be turned
off or deleted while nobody on the list counts, and a break-glass person is never linked to a provider by email.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-712-api.py` | passing |

In the console: the break-glass section of Settings › Sign-in is in progress; this use case stays at the api layer until
it ships.

## Non-vacuous check

`Wanjiru's password is now refused`: with the company-sign-in check in `passwords.py` removed, she signs in and the
check fails.
