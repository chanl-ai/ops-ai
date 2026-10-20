# Tables size each column by what it holds

Status: current. Id: `uc-257`. Service: `console`. Layers: ui.

Wide lists ran off the screen: the Workflows table measured 2745px at 1280 because a workflow's "Starts when" line
never wrapped. A column now says what it holds (an id, a date, a status, a name, a description, a number or money)
and the shared data table sizes it: ids, dates and statuses on one line at their own width; a name takes the free
space and trims to one line with the whole value on hover; a description wraps to two lines then trims; numbers and
money sit on one line, right-aligned; a cell that draws nothing shows a dash. On a phone the select box and the name
stay pinned while the other columns scroll. Before and after screenshots: `docs/console/proposed/table-columns/`.

## Preconditions

| Needs | How |
|---|---|
| Seeded workflows in Operations | the stack's seed |
| Priya to sign in | the platform seed |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Priya opens Workflows at 1280 | Each workflow's name and "Starts when" line is one line, trimmed with an ellipsis, and the whole name shows on hover |
| 2 | She reads the Runs · 24h column | Counts are right-aligned on one line |
| 3 | A cell of a sized column draws nothing | It shows a dash |
| 4 | At 400px she scrolls the table sideways | The name column stays pinned beside the select box; the page itself never scrolls sideways |
| 5 | Priya opens Workflows, then View, turns a hidden column on and reloads | Six data columns show by default; View lists the rest by name; the column she turned on is still shown |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-257-ui.mjs` | passing |
