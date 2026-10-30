# Password sign-in and reset

Status: current. Id: `uc-160`. Service: `platform-service`. Layers: api, ui (ui layer an earlier change).

## Preconditions

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Ravi asks for a reset on Forgot password, and one link is mailed to him | ui | 1 | 1 |
| S2 | The link opens the reset page, which takes his new password | ui | 3 | 3 |
| S3 | He signs in with the new password, and the demo password no longer works | ui | 5 | 5 |

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
| 1 | Ravi signs in with the demo password, then asks for a reset | 204; one mail to Ravi with a console `/reset-password/prt_…` link |
| 2 | Ask for a reset for an unknown email | 204 and no mail |
| 3 | Set a new password with the link, then use the link again | 204, then 400 `reset_invalid` |
| 4 | Read Ravi's earlier session | 401: the reset ended it |
| 5 | Sign in with the new password, then with the demo password | A `password` session; 401 |
| 6 | Step up with the new password | 200 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-160-api.py` | passing |
| ui | `platform-service/scripts/test-uc-160-ui.mjs` | passing: Forgot password, the reset page and the sign-in page |

## Non-vacuous check

`the link works once`: with the used-at condition removed from the reset, the second use answers 204 and the check
fails.
