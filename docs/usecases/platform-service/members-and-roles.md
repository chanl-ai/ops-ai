# Members and roles

Status: current. Id: `uc-023`. Service: `platform-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Free use-case ports | the runner picks free ports and its own database; or set the OPS_USECASE_* ports and OPS_USECASE_DB |

The script starts platform-service in dev on the run's database: its own migration chain, the dev seed (tenant
`local` (the tenant dev auth and every service seed use), team `team_ops` with Priya Shah admin, James Richardson builder, Maya Okafor approver, all on the demo
password `northfield-demo`), the public app and the internal one. No model is called. Invited addresses carry a per-run suffix, so a reused database never answers "already invited".

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya invites two people as admins | Two invitations, one link each |
| 2 | Priya demotes herself while the invitees have not accepted | Skipped with `last_admin` |
| 3 | The first invitee accepts | A session whose token already carries `team_ops` |
| 4 | Priya changes Maya to viewer | Applied; the member list shows it |
| 5 | The invitee creates a key; Priya removes the invitee; the invitee reads `/v1/me` | 401 |
| 6 | A service introspects the removed member's key | 401 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-023-api.py` | passing |

## Non-vacuous check

`demoting the only admin is skipped with a reason`: with the last-admin rule removed, Priya's demotion is applied
and the check fails.
