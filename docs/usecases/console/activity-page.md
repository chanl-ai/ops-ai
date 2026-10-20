# The one Activity page

Status: current. Id: `uc-141`. Service: `console` on agents-service `GET /v1/activity`. Layers: ui.

Runs, chats, emails received and Human Task decisions used to be listed in different places, so a person could not see
in one list what had happened in the team. Activity is that list. Channel, agent and workflow pages show a count and
link here filtered with `?source=<type>:<id>`; they do not keep lists of their own. The Audit log stays separate.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | A canvas workflow is saved and run through the API; James opens Govern › Activity | The run is a row named for its workflow, kind Workflow run, with its outcome |
| 2 | He filters Kind to Workflow run | The console asks the server with `kind=workflow_run` |
| 3 | He opens `/activity?source=workflow:<id>` as a workflow's View activity link does | Only that workflow's rows, a chip naming it, and Show all |
| 4 | He clicks the run row | The run's page opens |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-141-ui.mjs` | passing |
