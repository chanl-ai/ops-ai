# Only a person who may decide a review decides, resumes or replays it

Status: current. Id: `uc-782`. Service: `agents-service`. Layers: api.

Short title: Only a person who may decide a review decides, resumes or replays it

## Story

As a reviewer, I want only people who may decide a task to decide it, by any route and at any time, so that the
two-person rule holds even after someone has already decided.

## People

| Person | Role | Does what |
|---|---|---|
| Dana | member who asks | Asks the agent for a write and starts a workflow run; may not decide either while the two-person rule is on |
| Lee | reviewer | Approves Dana's write |
| Maya | reviewer | Approves the Human Task on Dana's run |

## In this example

In this example Dana tries to decide her own chat write and her own run's Human Task by every route, before and after a
reviewer decides it. It assumes the team turned the two-person rule on (requesterMayDecide off).

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | Dana cannot approve her own chat write, in Reviews, on the chat card or in a bulk decision | api | 1-4 | 2 |
| S2 | After Lee approves, Dana posting the same decision is refused and resumes nothing | api | 5-6 | 6 |
| S3 | Lee posting his decision again gets the approved review, and the chat goes on only once | api | 7 | 7 |
| S4 | After Maya decides Dana's Human Task, Dana's repeat is refused and Maya's is answered | api | 8-12 | 11 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Dana asks the fraud agent to hold a wire | The write waits on an approval card |
| 2 | Dana approves it in Reviews | 403 |
| 3 | Dana approves it on the chat card | 403 |
| 4 | Dana bulk-decides it | Nothing is decided; her task is skipped with the refusal |
| 5 | Lee approves it with a step-up | 200; the chat resumes once |
| 6 | Dana posts the same decision again | 403 |
| 7 | Lee posts the same decision again | 200, approved; no second resume |
| 8 | A workflow with one Human Task is made live | Live |
| 9 | Dana starts a run of it | The run waits on its task |
| 10 | Maya approves the task | 200 |
| 11 | Dana posts approve, then reject, on the decided task | 403 both times, before the decision is named |
| 12 | Maya posts approve again | 200, approved |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-782-api.py` | passing |

## Non-vacuous check

Steps 6 and 11. With the decider check removed from the replay branches (`hitl_facade.decide` and
`engine_reviews.decide`), step 6 and step 11 approve answer 200 and step 11 reject answers 409 already_decided, so
those three checks fail; seen on 2026-11-24.
