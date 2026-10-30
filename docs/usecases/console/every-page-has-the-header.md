# Every page draws the shared header

Status: current. Id: `uc-264`. Service: `console`. Layers: ui. Card: an earlier change.

Check-standards rule 12 finds `<PageLayout` or `<RecordLayout` in a page's imports, but a page can satisfy it from a
branch that never renders (a not-found state). This use case checks the rendered page instead.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and the demo seed | `make db-up`; the use-case stack seeds itself |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya opens every route in the sidebar | Each draws the shared header (`page-header`), except the chat workspace, a full-height shell |
| 2 | She opens one record of each kind: the first record each list links to, and a Human Task, a case, a run, a file, a workflow and an agent | Each draws the shared header |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-264-ui.mjs` | passing |
