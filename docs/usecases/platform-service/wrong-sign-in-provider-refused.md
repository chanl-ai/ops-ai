# A sign-in by another method or provider than the workspace's is refused

Status: current. Id: `uc-163`. Service: `platform-service`. Layers: api.

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
| 1 | Priya, a team admin outside the Security team, sets a provider | 403 |
| 2 | Sam makes the workspace SAML-only for a new domain | 200 |
| 3 | James signs in with the demo password | 401 |
| 4 | An answer to the workspace's SAML request signed by another provider's key | `error=sign_in_refused` |
| 5 | A person signs in at the configured provider; the code is used again | 200, then 401 |
| 6 | Start SSO for a domain with no provider | 400 `sso_not_enabled` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-163-api.py` | passing |

In the console: the sign-in page offers SSO for an SSO workspace (uc-161's ui script); the refused password, provider answer and reused code stay at the api layer.

## Non-vacuous check

`a password sign-in in the SAML-only workspace is refused`: with the workspace's password switch ignored, James
signs in and the check fails.
