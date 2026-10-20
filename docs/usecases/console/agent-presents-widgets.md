# An agent shows a table and a figure in chat with no tool behind them

Status: current. Id: `uc-089`. Service: `console`. Layers: ui.

The baseline for card c-082: today the kernel's built-in `present` tool lets the model turn facts already in the
conversation into a widget. No tool, connection or template is involved.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | James Richardson (builder); password `northfield-demo` |
| The scripted model | `call present <json>` calls the built-in present tool with those arguments |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James creates an agent with no tools and opens a chat with it | the thread opens |
| 2 | He asks it to compare two accounts' limits | a table titled "Wire limits" with 2 rows and columns account, daily and per_wire |
| 3 | He asks for the open disputes figure | a stat card "4 open disputes" with its change |
| 4 | He asks for a shape present does not allow | no widget; the model gets the refusal back and answers in text |
| 5 | Reload the thread | the same two widgets, drawn from the stored parts |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-089-ui.mjs` | passing |

## Non-vacuous check

Step 2 fails if the chat stream drops present's part: the turn answers in text and no widget draws.
