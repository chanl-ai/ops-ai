# Workflow approvals use agents-service workflows

Status: passing. Id: `uc-041`. Service: `tools-service`. Layers: api. Card: c-039.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| agents-service and tools-service | started by the script on the run's own ports, tools-service pointed at agents-service with `OPS_AGENTS_URL` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `GET /v1/workflow-refs` on agents-service with tools-service's service token | the workflows, seeded ones owned by `team_ops` |
| 2 | Request an approval on Core banking for `dispute_email` | 201, named as agents-service names it |
| 3 | The requester decides it | 403 |
| 4 | Someone else (X-Dev-User) approves it | 200, approved |
| 5 | `POST /v1/calls` as `workflow:dispute_email` | runs; the call log names the workflow |
| 6 | Request one for `wf_wire`, a fixture workflow agents-service does not have | 400 "Choose a workflow" |
| 7 | Create a workflow in agents-service under a team tools-service has no record of, then request one for it | 422 naming the team, never handed to the all-scope team |
| 8 | Stop agents-service, wait past the 30 s cache, request again | 503 `workflows_unavailable` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-041-api.py` | passing |

## Non-vacuous check

`a workflow whose team tools-service has no record of fails closed` was seen failing (the request was accepted, 201)
with the directory's fail-closed lookup replaced by the old fall-to-the-all-scope-team one. Steps 6 and 8 fail if
tools-service checks a fixture or answers from no data.
