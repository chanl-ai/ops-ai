# SAML sign-in and step-up at the same provider

Status: current. Id: `uc-162`. Service: `platform-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Free use-case ports | the runner picks free ports and its own database |

The script starts platform-service in dev on the run's database with the dev seed (tenant `local`, team `team_ops` with
Priya Shah admin, James Richardson builder, Ravi Menon viewer; team `team_security` with Sam Adeyemi admin; demo password
`northfield-demo`), its public and console URLs set, one OIDC client secret named `uc-oidc`, reset mail written to a
folder, and the local fake identity provider (`python -m ops_signin.fake_idp`) on the run's IdP port. No real
identity provider and no model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Sam sets a SAML provider (the fake provider's certificate) for a new domain | 200 |
| 2 | An analyst on the domain signs in at the provider | A `saml` session |
| 3 | Step up with a password | 401 `wrong_method` |
| 4 | Step up at the provider, which reuses its earlier login | `error=sign_in_refused`, `stepUp=1` |
| 5 | Step up at the provider with a fresh login | A step-up token; the console is sent back to `/reviews` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-162-api.py` | passing |

## Non-vacuous check

`a provider that reuses its earlier login does not pass a step-up`: with the login-time check removed, the step-up
completes and the check fails.
