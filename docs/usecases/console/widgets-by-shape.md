# Chat widgets draw by shape

Status: current. Id: `uc-073`. Service: `console`. Layers: ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| platform-service's dev seed | James Richardson; password `northfield-demo` |
| The console dev server | `/dev/widgets` answers 404 outside development |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Open `/dev/widgets`, which draws every part in `apps/console/src/lib/widgets/sample-parts.json` | each shape draws with its default (rows table, series line, record fields, metric stat, form, decision approval card, steps task); the part whose hint prefers `bar` draws as a bar chart |
| 2 | Read the switches | chartable rows offer Table, Line, Bar and Area; rows with no numeric column offer none |
| 3 | Page the 23-row transactions table | 10 rows a page, Page 1 of 3; Next shows the 11th row |
| 4 | Switch rows to Line chart and the series to Table | two lines drawn; the table's columns are week, Chequing, Savings |
| 5 | Submit the form | Submit waits for Phone; the recorded values include the default slot |
| 6 | Approve the decision | the recorded action carries the hold id; the card reads Approved |

The page's actions are recorded on the page, not sent to a service. The same parts go through the real chat stream in
uc-061 once agents-service emits widget parts (an earlier change T004, T007).

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-073-ui.mjs` | passing |

## Non-vacuous check

Step 1 fails if the registry ignores `hint.prefer`: the bar sample draws as a table.
