# Members and roles

Status: current. Id: `uc-023`. Service: `platform-service`. Layers: api, ui.

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

## UI layer (c-077)

A console signed in through platform-service, with tools-service beside it. Invited addresses carry a per-run suffix.

| # | Step | Expected |
|---|---|---|
| 1 | Priya opens Access | The team from `GET /v1/settings/members`; James is Builder, Maya Reviewer; no Last active or Team column (the service sends neither), and Role is on screen at 400 px |
| 2 | Priya invites a new address as viewer | The dialog is one form titled "Invite to Operations", says no email is sent and the link is shown once, and offers no Team field; the link, shown once, is `/invite/<token>`; the invited row then offers no link |
| 3 | The link in a fresh browser; the newcomer gives a name and joins | Names Priya, Operations and Viewer; no password asked; signed in with `team_ops: viewer` |
| 4 | The newcomer opens Access and Tools, and posts a module to tools-service | No Invite, no Import operations; 403 `role_required` |
| 5 | Priya opens Access | The newcomer is Active, Viewer |
| 6 | The link again; a second accept | The used page; 409 `invite_used` |
| 7 | James opens Access and posts an invite | No Invite; 403 `admin_required` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-023-api.py` | passing |
| ui | `platform-service/scripts/test-uc-023-ui.mjs` | passing |

## Non-vacuous check

`demoting the only admin is skipped with a reason`: with the last-admin rule removed, Priya's demotion is applied
and the check fails.

UI layer: with the console's platform adapter not applied (members, invites and audit left on the mock), steps 1 to 6
fail (`.codeloop/evidence/077/red-adapter-off.txt`).
