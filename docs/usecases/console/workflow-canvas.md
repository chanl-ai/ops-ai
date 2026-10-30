# A builder designs a workflow on a canvas that fills the page

Status: current. Id: `uc-121`. Service: `console`. Layers: ui.

an earlier change (split from an earlier change), owner feedback (mid-1): the workflow editor's canvas fills the page under the header at a
readable zoom, with its controls, checks and minimap floating over it, instead of sitting between two side columns.

## Preconditions

| Needs | How |
|---|---|
| The demo stack | the ui harness with `demo: true`: platform sign-in as James; the script saves a ten-step draft through `POST /v1/workflows/definitions` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Open the ten-step workflow at 1440px | The sidebar collapses; the canvas is wider than 1200px; Save version is in the page header; no settings column |
| 2 | Read the zoom | At least 0.65, with the trigger inside the canvas |
| 3 | Fullscreen, then Escape | The canvas takes 1440 by 900, then returns; every canvas button has a name |
| 3b | Click the hold step once | Its settings sheet is in the page by the next frame |
| 4 | Clear the hold step's operation | The step is marked with an error, the count says 1 error, and the list names `operation` |
| 4b | Open a workflow whose trigger fans out to two steps that meet again with no Join | It saves with a warning; that step is marked, and the count says 1 warning, not an error |
| 5 | Open it at 400px | The page does not scroll sideways |
| 6 | Leave for the workflows list | The sidebar is expanded again |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-121-ui.mjs` | passing |
