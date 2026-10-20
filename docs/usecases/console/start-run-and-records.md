# Starting a run, and reading a run and a case

Status: current. Id: `uc-228`. Service: `console` on agents-service. Layers: ui. Card: c-266.

A run starts from the workflow list or from the editor, and a run and a case each open on their own page. The walk
opens each surface and keeps a screenshot of it, so a refactor of the dialogs or the detail layout can be compared side
by side before and after.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James presses Start run on Workflows, scrolls the picker, searches a workflow and an agent, picks the workflow and presses Next | The picker offers every workflow the server counts and no agent; the search finds the workflow; Next opens that workflow's own Start a run form |
| 2 | He presses Test run in a workflow's editor | The dialog names the workflow and offers a test run on the latest version |
| 3 | He opens the test run | The run page shows the workflow's name, the run's id and its status; in the rail the definition reads in full on hover, and it and the digest each have a copy button |
| 4 | He opens a case | The case page shows its subject and customer |
| 5 | At 400 px he opens the run and the case | Nothing scrolls sideways |
| 6 | A workflow opens a case with fields, and James opens the case | The case's Fields panel lists every field the workflow gave it, dates formatted and numbers grouped, named as the workflow named them |
| 7 | James opens the runs list once the run has ended | Its row says how it ended: the outcome its End step names, or the error that stopped it |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-228-ui.mjs` | passing |
