# A team's running work is counted for that team only and stops its deletion

Status: passing on origin/main 40064381 (api). Id: `uc-platform-1`. Service: `platform-service`. Layers: api.

Before a team is deleted, platform-service asks agents-service what still runs in it. The answer counts the team's
runs in progress and names its live workflows. It counts nothing from another team. The Delete card on the team's
settings page reads the platform-service answer, and the team is deleted only after it is archived for the window with
no live workflow.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A builder's live workflow and queued run show in the team's count | api | 1 | 1 |
| S2 | A new team beside it counts nothing | api | 2 | 2 |
| S3 | The delete check names the workflow and the run, and says the team cannot go | api | 3 | 3 |
| S4 | An active team cannot be deleted until it is archived | api | 4 | 4 |
| S5 | An archived empty team still waits out its days | api | 5 | 5 |
| S6 | A builder cannot read the check or delete a team | api | 6, 7 | 6 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL | `make db-up` |
| The run | `make usecase-test UC=uc-platform-1 LAYER=api` |

The script starts platform-service with the dev seed and agents-service on platform sign-in, and points
platform-service at this run's agents-service (a shell that names another stack's agents URL would otherwise answer).
Wanjiru Kamau, a workspace admin, creates the team Treasury with Ravi Menon as its admin. James Richardson, a builder
in team_ops, makes a workflow live (Maya Okafor approves it when the stack asks for a second person) and starts one
live run that no worker takes. The seed's own team_ops workflows are in the counts, so the checks compare with the
counts read before James adds his.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | James saves and publishes a workflow, then starts one run | Stage live; the run is accepted (202) |
| 1 | James reads `GET /v1/teams/usage` on agents-service | One more run in progress than before; the workflow's name added to the live list |
| 2 | Ravi reads it for Treasury | 0 runs, no live workflows |
| 3 | Wanjiru reads `GET /v1/settings/teams/team_ops/delete-check` | usage known; the same live list and run count; `canDelete` false |
| 4 | She deletes team_ops | 409 `not_archived` |
| 5 | She archives Treasury and reads its check | archived, usage known, nothing live, 0 runs, 30 days left, `canDelete` false |
| 6 | James reads the check for team_ops | 403 |
| 7 | James deletes Treasury | 403 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `platform-service/scripts/test-uc-platform-1-api.py` | passing (12 checks, four of them sign-ins) |
| sdk | none | The SDK has no teams module; a settings module is the next SDK addition |
| ui | none | The Delete card is not driven yet; the team settings page is covered by uc-164 (which fails on main) |

## Non-vacuous check

`2 Treasury counts nothing` pairs with step 1: with the team filter removed from `team_usage`
(`services/agents-service/src/ops_agents/api/routers/team_usage.py`), Treasury would report James's workflow and
step 2 fails. Step 3 fails when platform-service reads another agents-service than the run's.
