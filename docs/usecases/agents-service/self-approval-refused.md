# Self-approval is refused

Status: current. Id: `uc-009`. Service: `agents-service`. Layers: api.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents :8790 |

The script starts platform-service and the agents service on the scripted model, with platform sign-in so each person
carries their roles. James is a Builder, whose role lacks Approvals · decide; Priya is the team's Admin, whose role
has it. A person decides their own request only while a role they hold has that cell (Access › Roles).

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | As James (platform sign-in), ask the fraud agent to hold wire W-88213 | The reply pauses on an approval |
| 2 | As James, step up and approve | 403, "someone else has to decide it" |
| 3 | As Priya, step up and approve | 200, approved |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-009-api.py` | passing |

In the console: uc-086's ui script, steps 9 and 10: the person whose chat drafted the write sees who decides and no Approve of their own, and a reviewer of the team approves it in Human Tasks.

## Non-vacuous check

`Dana approving her own request is refused` paired with `Lee approving it succeeds`: the same request and the same
kind of step-up pass for a different person, so the refusal is about who decides.
