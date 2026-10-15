# Audit

Status: current. Id: `uc-025`. Service: `platform-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Free use-case ports | the runner picks free ports and its own database; or set the OPS_USECASE_* ports and OPS_USECASE_DB |

The script starts platform-service in dev on the run's database: its own migration chain, the dev seed (tenant
`local` (the tenant dev auth and every service seed use), team `team_ops` with Priya Shah admin, James Richardson builder, Maya Okafor approver, all on the demo
password `northfield-demo`), the public app and the internal one. No model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya invites a viewer; read the audit | One `member.invite` entry with Priya as actor, a request id and the member as target |
| 2 | The invitee accepts | A `member.accept` entry |
| 3 | Priya changes the member's role | A `member.role` entry |
| 4 | Priya removes the member | A `member.remove` entry |
| 5 | Maya, made a viewer, reads `/v1/audit` | 403 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-025-api.py` | passing |

## Non-vacuous check

`a viewer reading the audit is 403`: with the admin check on the audit route removed, Maya reads it (200) and the
check fails.
