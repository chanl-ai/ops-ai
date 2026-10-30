# Roles and permissions

Status: current. Id: `uc-118`. Service: `platform-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| Free use-case ports | the runner picks free ports and its own database; or set the OPS_USECASE_* ports and OPS_USECASE_DB |

The script starts platform-service in dev on the run's database: its own migration chain (0006 writes the built-in
roles) and the dev seed, which gives every seeded membership its built-in role (tenant `local`; `team_ops` with Priya
Shah admin and James Richardson builder; `team_security` with Sam Adeyemi admin), all on the demo password
`northfield-demo`. No model is called. James is made a viewer and back, so a reused database ends as it started.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya reads `GET /v1/roles` | Admin, Builder, Reviewer, Viewer, Security admin, Chat user and Owner, in that order |
| 2 | Priya reads `GET /v1/roles/chat_user` | Its grid grants `chat.view` (own), `chat.run` (all) and `memory.edit` (own), and nothing else |
| 3 | Priya reads `GET /v1/me/permissions` | In Operations, `access.manage` granted by Admin; `secrets_egress.manage` from Admin is marked Security-team only, so it does not apply in Operations |
| 4 | Sam reads `GET /v1/me/permissions` | In Security, `secrets_egress.manage` granted by Security admin (and Admin) and marked Security-team only |
| 5 | Priya reads James's permissions | `agents.create`; `knowledge.edit` for all of the team's knowledge; no `agents.decide` |
| 6 | Priya reads Sam's permissions | 404: they share no team |
| 7 | Priya makes James a viewer; James signs in again | His token's `perm_version` is higher; `agents.create` is gone and `agents.view` comes from Viewer |
| 8 | Priya makes James a builder again | Applied |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-118-api.py` | passing |

In the console: uc-267's ui script lists every role with what it grants, opens a person on their effective access with the role that grants each action, and checks an action by the services' own check.

## Non-vacuous check

`James no longer creates agents and reads as Viewer`: with the member role route's assignment update removed
(`store/members.py`, the `_mirror` call in `set_role`), James still holds `agents.create` from Builder and the check
fails. Step 5 shows he held it before the change.
