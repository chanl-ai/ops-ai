# A builder sets a write's approval policy

Status: current. Id: `uc-059`. Service: `console`. Layers: ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| platform-service's dev seed | James Richardson (builder) and Priya Shah (admin) in Operations; password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James adds a write operation to a draft module and opens it on the module page | the row has no "Two approvers"; the sheet says "Approved by Operations" |
| 2 | He picks "Two different people" and stages the change | the PATCH carries `approvers: 2`; the operation comes back with it and per-call approval on; the sheet has no self-approval switch (the tenant's requesterMayDecide policy decides that, c-186) |
| 3 | He closes the sheet | the row reads "Two approvers"; the sheet line reads "Approved by Operations" |
| 4 | A fresh read of the module | `approvers` 2, `approverTeam` team_ops, no `selfApproval` |

The approving team picker offers the signed-in person's own teams and the operation's current team, because
platform-service lists only the caller's teams (c-048 T018, G25). In the seed James cannot pick Security
until a workspace-wide team list exists (G31 on c-051).

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-059-ui.mjs` | passing |

## Non-vacuous check

Step 2 fails if the sheet leaves the policy out of the patch: the PATCH has no `approvers`, and the row never reads
"Two approvers".
