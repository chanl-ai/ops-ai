# An agent is applied from a spec file and read back the same

Status: draft. Id: `uc-agents-2`. Service: `agents-service`. Layers: api.

Short title: Apply an agent spec file

A developer keeps an agent as one file in their repository (docs/design/agents-v2/agent-spec-file.md). They check it,
apply it to an agent, read it back unchanged, and see what a changed copy would change before applying it. A file that
breaks a rule is refused with the path of each field at fault, and nothing is saved. The console's agent page reads the
same saved version.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A file is checked, applied and read back equal | api | 1-3 | 3 |
| S2 | A bad file is refused with the field's path, and nothing is saved | api | 4-5 | 5 |
| S3 | A changed copy shows what applying it would change | api | 6 | 6 |
| S4 | A copy made from an older version is refused | api | 7 | 7 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL | `make db-up` |
| The run | `make usecase-test UC=uc-agents-2 LAYER=api` |

agents-service runs on the scripted model with its fixture tools and knowledge bases, on a database the run owns. The
file names tools and a knowledge base the fixture offers; it names no helper agent, skill or guardrail, so nothing else
needs making. No model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Make an agent, then `GET /v1/agents/{id}/spec` | 200; `version`, `digest` and a document holding the agent's name |
| 2 | `POST /v1/agents/spec/validate` with a supervisor file for an insurance claims desk | 200; `ok` true, no problems, a summary with the loop kind and the tool count |
| 3 | `PUT /v1/agents/{id}/spec` with that file and the version and digest of step 1, then `GET` it | 200; the document read back equals the file applied; `GET /v1/agents/{id}` answers the same digest |
| 4 | Validate a copy with an unknown loop field and a tool nobody offers, then with the field fixed | 200; `ok` false; first one problem at `/loop/maxStepz` (the schema is checked before any record is looked up), then one at the tool's index under `/toolIds` |
| 5 | `PUT` that copy | 422 `spec_invalid` with the same paths; the agent's version and digest are those of step 3 |
| 6 | `POST /v1/agents/{id}/spec/diff` with the budget ceiling raised | 200; one change, `replace` at `/limits/budget/ceilingUsd` |
| 7 | `PUT` a file with the version and digest of step 1 | 409 `stale_base` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-agents-2-api.py` | Written, not yet run on a stack |
| sdk | none | `ops.agents.apply`, `spec`, `validate` and `spec_diff` are not written yet |
| cli | none | `opsai agents apply`, `export`, `validate` and `diff` are not written yet |
| ui | none | View as file on the agent page is not built yet |
