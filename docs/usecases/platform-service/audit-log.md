# Audit

Status: current. Id: `uc-025`. Service: `platform-service`. Layers: api, ui.

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

## UI layer (c-077)

| # | Step | Expected |
|---|---|---|
| 1 | Priya invites a viewer and the newcomer accepts (through the API); Priya opens the audit log | Rows "Invited <email> as viewer" by Priya Shah and "<email> accepted the invitation and joined" by the newcomer, from `GET /v1/audit`; Export is offered |
| 2 | Priya opens Access changes | Its count equals the service's `viewCounts.access`; only member and key entries |
| 3 | James, a builder, opens the audit log | "Only a team admin reads the audit log" with no Export button; the service answers 403 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-025-api.py` | passing |
| ui | `platform-service/scripts/test-uc-025-ui.mjs` | passing |

## Non-vacuous check

`a viewer reading the audit is 403`: with the admin check on the audit route removed, Maya reads it (200) and the
check fails.

UI layer: with the console's platform adapter not applied, steps 1 to 3 fail (`.codeloop/evidence/077/red-adapter-off.txt`).
