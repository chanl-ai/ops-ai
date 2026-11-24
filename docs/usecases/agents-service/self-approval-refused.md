# Self-approval is refused

Status: current. Id: `uc-009`. Service: `agents-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents :8790, tools :8791, platform :8810 and :8811 |

The script starts platform-service and the agents service on the scripted model, with platform sign-in so each person
carries their roles. James is a Builder, whose role lacks Approvals · decide; Priya is the team's Admin, whose role
has it. A person decides their own request only while a role they hold has that cell (Access › Roles). Steps 4 to 10
run a second stack: tools-service, platform-service, the agents service and an engine worker, with real tokens. A
run's starter approves their own write only while they hold the cell, asked of platform-service at the review step
and again where tools-service sends the write.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | As James (platform sign-in), ask the fraud agent to hold wire W-88213 | The reply pauses on an approval |
| 2 | As James, step up and approve | 403, "someone else has to decide it" |
| 3 | As Priya, step up and approve | 200, approved |
| 4 | As Priya, turn on asking a reviewer before the team's writes (Govern › Approvals), then save and publish two fee waiver workflows: one whose write waits on a review, one with a second look after it | Both live |
| 5 | As James, start the first | The run waits on the review; nothing is sent |
| 6 | As James, approve that review | 403 |
| 7 | As Priya, start the first | The review is decided as hers and the write is sent; the run succeeds |
| 8 | As Wanjiru (workspace admin), make a Loan officer role with Approvals · view and decide, and give it to James in the team | 201 |
| 9 | As James, start the second | His review is decided as his own; the run waits on the second look |
| 10 | As Wanjiru, untick Approvals · decide on Loan officer; as Priya, approve the second look | The send is refused with `own_request` and the run ends failed |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-009-api.py` | passing |

In the console: uc-086's ui script, steps 9 and 10: the person whose chat drafted the write sees who decides and no Approve of their own, and a reviewer of the team approves it in Human Tasks.

## Non-vacuous check

`James approving his own request is refused` paired with `Priya approving it succeeds`: the same request and the same
kind of step-up pass for a different person, so the refusal is about who decides. Step 10 against step 7: the same
write, approved as its starter's, is sent for an Admin and refused once the cell is unticked. Step 10 fails when
tools-service's own-request check answers yes without asking (`OwnRequests.refusal` returning None).
