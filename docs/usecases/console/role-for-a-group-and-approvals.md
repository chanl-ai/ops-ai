# A role given to a group opens the approvals cell for its members

Status: draft. Id: `uc-766`. Service: `console`. Layers: ui.

A custom role can hold the approvals cells, and a group can hold a role. A person in the group holds what the role
gives, in the team it was given in. Approvals (Settings) shows its switches to a person without the manage cell and
leaves them off; once the person's group holds a role with the cell, the same page lets them change the rules. The
admin gives the role from its page (Give role, one searched list of people and groups). No route or screen makes a
group yet, so this case seeds the group holding Ravi in `lib/group_role.py`.

## Preconditions

| Needs | How |
|---|---|
| A stack with platform sign-in | the ui harness with `platform: true`; Wanjiru is the workspace admin, Ravi a viewer in Operations |
| A custom role holding approvals view and manage | Wanjiru makes it through `POST /v1/roles` |
| A group holding Ravi | `lib/group_role.py` (the store; no route makes a group) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Wanjiru opens the role | Its grid has the approvals view and manage cells; it is held by 0 |
| 2 | Ravi opens Settings, Approvals | The "Ask before an agent changes anything in an app" switch is off (disabled) |
| 3 | Wanjiru gives the role to Ravi's group from the role's page: Give role, search the group, Give role | The picker lists the group once; the give answers 201 and the page reads "held by 1" |
| 4 | Ravi signs in again and opens Approvals | The switch can be changed |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `scripts/test-uc-766-ui.mjs` | draft |

## Non-vacuous check

Steps 2 and 4: the same page, the same person, the switch disabled before the group holds the role and enabled after.
