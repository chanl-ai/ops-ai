# An agent finds a workflow with search_tools and runs it; its agent step answers by schema

Status: current. Id: `uc-084`. Service: `agents-service`. Layers: api, ui. Card: c-062.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | the runner picks free ports and a database of its own |

The script builds the banker demo's stack (harness `demo()`: models-service on the fake OpenAI with the committed
demo rules, tools-service with the core bank fake, kb-service) and starts a workflow runner worker. No model key is
needed and no real model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `GET /v1/tools` | `workflow:customer_summary`, the seeded v2 workflow, is listed with its input schema (`customer`) |
| 2 | Chat with `ag_advisor`: "Run the customer summary workflow for Priya Natarajan." | The agent calls `search_tools`, which returns `workflow__customer_summary` |
| 3 | The agent calls `workflow__customer_summary` | The tool output carries `runId`, `workflow`, `status: finished` and `outcome {customerId: CUS-1002, summary}`; the reply quotes the summary |
| 4 | `GET /v1/runs/{runId}` | The run first finds the customer by name (`find`, search_customers, then `found`) and reads their record (`read`, get_customer); the `summarise` step (ops.ai.agent, ag_advisor with the output schema) shows that record in its input and the schema's output through the ok port; the run's outcome is `summarised` |
| 5 | `PATCH /v1/agents/ag_advisor` without the grant (published), then the same chat | `search_tools` does not return the workflow |
| 6 | Chat "Start the customer summary workflow directly for Priya Natarajan." (a forced fake rule calls the tool by name) | The call is refused and no run of `customer_summary` starts |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-084-api.py` | passing |
| ui | `agents-service/scripts/test-uc-084-ui.mjs` | passing |

## Non-vacuous check

`the agent searches its tools and finds the workflow`. Run with `UC084_UNGRANTED=1` (the grant dropped before the
first chat) and it fails, as do the run and outcome checks: an agent finds only the workflows it holds. Step 6 guards
the grant filter itself: with `ChildRuns.offers` offering every v2 workflow regardless of the grant, the direct call
ran (`FAIL ... a direct call to the workflow is refused and starts no run`).
