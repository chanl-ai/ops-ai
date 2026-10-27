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
| 1 | James adds a write operation to a draft module and opens it on the module page | the row has no "Two approvers"; the sheet names no approving team and has no team picker (a held write is decided by its run's team, c-509) |
| 2 | He picks "Two different people" and stages the change | the PATCH carries `approvers: 2`; the operation comes back with it and per-call approval on; the sheet has no self-approval switch (the tenant's requesterMayDecide policy decides that, c-186) |
| 3 | He closes the sheet | the row reads "Two approvers" |
| 4 | A fresh read of the module | `approvers` 2, no `selfApproval` |

An operation names no approving team: a held write is decided by people of its run's team (c-509), so the sheet has
no team picker, and tools-service accepts and ignores an `approverTeam` an older caller still sends.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-059-ui.mjs` | passing |

## Non-vacuous check

Step 2 fails if the sheet leaves the policy out of the patch: the PATCH has no `approvers`, and the row never reads
"Two approvers".
