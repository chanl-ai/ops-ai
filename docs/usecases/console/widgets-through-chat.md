# Tool results draw as widgets through chat

Status: current. Id: `uc-061`. Service: `console`. Layers: ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| platform-service's dev seed | James Richardson (builder), Priya Shah (admin), Nadia Petrov (Security); password `northfield-demo` |
| The fake bank | the ui harness serves `/v1/openapi-shapes.json`, one read per shape |
| The scripted model | `call <tool> <json>` calls a granted tool |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James discovers the insights spec | one read per shape; tools-service keeps `balance_history`'s declared `x-ops-shape` of rows on import (discovery does not show it) |
| 2 | He imports it, Nadia approves it, and an agent is granted all six reads | the agent can call each |
| 3 | In chat he asks for each read | the account draws as fields, transactions, balances and statement lines as tables (balances declared rows, so not a chart), daily spend as a line chart, open disputes as a stat |
| 4 | Read the transactions table and the stat | titled "transactions", 10 rows with Page 1 of 2; "3 cases" |
| 5 | Read the profile answer | a tool card and no widget: a nested answer fits no shape |
| 6 | Read the statement lines table (250 lines) | "Showing 200 of 250 rows"; 20 pages of 10 |
| 7 | Switch daily spend to Table | columns date, groceries, transit |
| 8 | Reload the thread | the same widgets, drawn from the stored parts |

agents-service shapes each tool result into a part (an earlier change T004); the console's widget registry picks the renderer
(T005, T006). Neither side names a tool in a part.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-061-ui.mjs` | passing |

## Non-vacuous check

Step 3 fails if the message view ignores `parts`: no widget draws, and the six answers show only as tool cards.
