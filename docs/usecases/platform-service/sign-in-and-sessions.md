# Sign in, session, refresh, sign out

Status: current. Id: `uc-021`. Service: `platform-service`. Layers: api, ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Free use-case ports | the runner picks free ports and its own database; or set the OPS_USECASE_* ports and OPS_USECASE_DB |

The script starts platform-service in dev on the run's database: its own migration chain, the dev seed (tenant
`local` (the tenant dev auth and every service seed use), team `team_ops` with Priya Shah admin, James Richardson builder, Maya Okafor approver, all on the demo
password `northfield-demo`), the public app and the internal one. No model is called. Platform tokens live two seconds in this run, so one expires inside it.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James signs in | A token and a refresh token |
| 2 | Read the session with the token | James, builder on `team_ops` |
| 3 | Read it again after the token's TTL | 401 |
| 4 | Refresh | A fresh token that resolves |
| 5 | Refresh again with the first, rotated refresh token | 401 |
| 6 | Read the session with the fresh token | 401: the reuse ended the session |
| 7 | Sign in again, sign out, read the session | 204, then 401 |
| 8 | Refresh with the signed-out session's refresh token | 401 |
| 9 | (console) A Platform admin invites James to Platform; he accepts and signs in afresh | The switcher reads Operations, his own team, and every call to agents-service names team_ops |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-021-api.py` | passing |
| ui | `platform-service/scripts/test-uc-021-ui.mjs` | passing |

## Non-vacuous check

`the reuse ended the session for its current token too`: with the revocation on reuse removed, the fresh token
still resolves (200) and the check fails.
