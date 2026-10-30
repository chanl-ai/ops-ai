# Workflow approvals use agents-service workflows

Status: passing. Id: `uc-041`. Service: `tools-service`. Layers: api. Card: an earlier change.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| agents-service and tools-service | started by the script on the run's own ports, tools-service pointed at agents-service with `OPS_AGENTS_URL` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `GET /v1/workflow-refs` on agents-service with tools-service's service token holding `workflows:view` | the workflows, seeded ones owned by `team_ops` |
| 2 | Request an approval on Core banking for `dispute_email` | 201, named as agents-service names it |
| 3 | Read the request | It names its system workflow run, `tool_access.requested:<id>`; Human Tasks decides it (uc-053) |
| 4 | Decide it on the module | 409 `decided_in_reviews` |
| 5 | `POST /v1/calls` as `workflow:dispute_email` | runs; the call log names the workflow |
| 6 | Request one for `wf_wire`, a fixture workflow agents-service does not have | 400 "Choose a workflow" |
| 7 | Create a workflow in agents-service under a team tools-service has no record of, then request one for it | 201, for that workflow's own team, never handed to every team; a workflow no team owns is refused (422) |
| 8 | Stop agents-service, wait past the 30 s cache, request again | 503 `workflows_unavailable` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-041-api.py` | passing |

In the console: an access request is decided in Human Tasks (uc-053's ui script); how tools-service reads agents-service's workflow list has no page of its own.

## Non-vacuous check

Step 7 checks the request is accepted and that agents-service names `team_nobody` as the workflow's team; the approval
does not expose the team its grant is for, so the step cannot see a grant handed elsewhere. Steps 6 and 8 fail if
tools-service checks a fixture or answers from no data.
