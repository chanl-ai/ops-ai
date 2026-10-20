# A run shows its workflow graph read-only with what passed, failed and was skipped

Status: current. Id: `uc-115`. Service: `console`. Layers: ui.

c-097, owner feedback (mid-2): a run opens on the workflow's own canvas, read-only, each step marked passed, failed or
skipped, with its input and output one click away, so a failure is found in seconds instead of in the step table.

## Preconditions

| Needs | How |
|---|---|
| The demo stack | the ui harness with `demo: true` and a workflow runner worker: platform sign-in, the seeded v2 customer summary workflow, the scripted model |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Run customer summary for Priya Natarajan; open the run | Request, Summarise and Summarised passed; No summary skipped |
| 2 | Run it for a customer the scripted model does not know; open the run | Summarise failed; No summary passed; Summarised skipped |
| 3 | Click the failed step | The step sheet shows its input (the customer) and its error |
| 4 | Save a three-step workflow with no node positions, run it and open the run | The canvas lays it out as the editor does: no two nodes on one spot |
| 5 | Open that run while the workflow cannot be read (the request answers 500) | The Graph section shows an error with Retry; while it loads it shows a placeholder |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-115-ui.mjs` | passing |
