# Basic workflow nodes run through the queue and survive a worker crash

Status: current. Id: `uc-081`. Service: `agents-service`. Layers: api. Card: c-061 slice 1.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | the runner picks free ports and a database of its own |

The script starts its own agents-service (scripted model), tools-service with the core bank fake behind it, and
worker processes (`python -m ops_agents.api.worker`) that it kills. No model key is needed and no model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `POST /v1/workflows/definitions` with a YAML v2 definition: request trigger, set fields, if, `get_customer` on the core bank, human review, ends; then `POST /v1/workflows/definitions/{id}/publish-requests` | 201, every check passes; the saved version is a draft until its publish request is approved (dev auto-approve), then live |
| 2 | `POST /v1/runs` with no worker running | 202; after 2 s the run is still `queued` |
| 3 | Start a worker | The run reaches the review (`waiting`); `GET /v1/runs/{id}/events` returns started, node steps and waiting_review, and nothing after the last seq |
| 4 | `GET /reviews/{runId}`, then decide `approved` | The review shows the customer the tool looked up; the run ends `succeeded`, outcome `approved` |
| 5 | `GET /v1/runs/{id}` | Each step's input, output and port from the journal |
| 6 | Second run on a worker started with `OPS_ENGINE_FAULT_KILL_AFTER_NODE=lookup` | The worker dies by SIGKILL right after the tool step's row is recorded; the run stays `running` |
| 7 | Start a new worker | It takes the run over after the lease lapses, reaches the review; a rejection ends it `rejected` |
| 8 | tools-service `GET /v1/executions?thread=<run>` | `get_customer` called exactly once for the second run |

## The ui layer

On the demo stack (core bank fake and its module), signed in as James: the editor at `/workflows/definitions/<id>`
draws the nine nodes with the ports their server types declare and only the server's checks; a parameter the schema
refuses (entered under All settings, the JSON beside the node's form) flags that node and blocks Save until fixed. Start run in the editor, a test run since the definition is a draft, opens `/workflows/runs/<run>`, queued with
no step while no worker runs; a worker killed after the tool step and a second that takes over bring it to the review;
the tool step shows one attempt, its port and output, and the gateway's log holds one get_customer call. With
OPS_ENGINE_FAULT_IGNORE_RECORDED=1 the last check fails (2 attempts, 2 calls).

The Workflows list holds both kinds (GET /v1/workflows joins v2 rows on the server, Kind column). New workflow
offers a runner workflow first: it publishes a request trigger wired to an end and opens it in the editor. Searching
the list finds it as "Runner · v2" and a draft, its row opens the editor, and Delete on the list removes the draft
(204, then 404); the workflow that has run answers 409 to a delete.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-081-api.py` | passing |
| ui | `agents-service/scripts/test-uc-081-ui.mjs` | passing |

## Non-vacuous check

`tools-service's executions show the tool called exactly once across the crash`. The kill lands after the step's
journal row and before LangGraph saves the step, so LangGraph runs the tool node again; only the wrapper's
recorded-output lookup keeps the second call from happening. Run with `OPS_ENGINE_FAULT_IGNORE_RECORDED=1` (the
lookup off) and the check fails with 2 calls.
