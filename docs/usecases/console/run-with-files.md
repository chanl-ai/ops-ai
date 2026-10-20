# A workflow runs from a form, with files attached

Status: current. Id: `uc-233`. Service: `console` on agents-service and files-service. Layers: ui. Card: c-273.

A builder tests a workflow without writing JSON: Start run shows a form generated from the Request trigger's input
schema, and a file input uploads files (to Files first) or picks ones already there. The run gets the files' ids.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James saves a workflow whose Request trigger takes files, a note, an amount, a date, a yes or no and a choice, and presses Test run | The dialog shows a Files field with an upload and a picker, one control per other input, and a JSON tab |
| 2 | He uploads TEST012.pdf, checks the JSON tab, and starts the test run | The JSON tab holds the uploaded file's id and name; the run starts in test mode with `files: [{fileId, name}]` as its input |
| 2b | He opens the run he started | Its Files row links TEST012.pdf by name to the file |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-233-ui.mjs` | passing |
