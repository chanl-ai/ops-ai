# Steps read in sentences wherever a person reads them

Status: current. Id: `uc-508`. Service: `console` on agents-service. Layers: ui. Card: an earlier change.

A workflow's steps are worded once, by the API, and every page a person reads draws those words: Activity's rows, a
Human Task's "What it changes", the case list's first response and the run page. Before this, each page worded steps
itself and fell back to names a builder chose: Activity titled calls `list_accounts`, the Human Task labelled a write's
input keys in the browser, the Run panel printed the workflow's id and the outcome's key, and a case's first response
had no writer, so its clock ran until it breached. The use case runs on the demo stack with a worker: James starts a
copy of the seeded `customer_hold` workflow (named "Hold on a customer's account (uc-508)") for Marcus Bell, Maya
approves the hold after re-entering her password, and James adds a note to the case the run opens.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James starts the hold copy for Marcus Bell, 2,140.55, test run | The run waits on a Human Task |
| 2 | He opens Activity filtered to the workflow | The calls read "Search customers: …" and "List accounts: …"; no row shows an operation, node or workflow id |
| 3 | Maya opens the Human Task | The task carries the write's fields as the operation labels them and a sentence; no label is an input key |
| 4 | Maya approves; the run places the hold and opens a case; James adds a note and shows First response from View on the case list | Before the note the case has no first response (the run's own events do not count); after it, First response reads Met |
| 5 | James opens the run page | The Run panel reads "Outcome Held" and "Hold on a customer's account (uc-508) v1", not `held` or `uc508_hold`; the story has "Maya Okafor approved: …" and no step names |
| 6 | Every page at 1280 and 400 px | No page errors and no sideways scroll |

Screenshots are saved under `evidenceDir('508', 'uc')`. Set `OPS_USECASE_DB` to a fresh name when the shared
`ops_usecase` database holds rows an older checkout wrote (a tools migration then fails on `ck_module_operations_access`).

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-508-ui.mjs` | passing |

## Non-vacuous check

Run on a clone at `dd22f660`, the commit before an earlier change's first change, steps 2 to 5 fail: Activity titles
`list_accounts` and `search_customers`, the task carries no labels, First response reads due after James's note, and
the Run panel reads "Outcome held" and "uc508_hold v1" (`uc-red.txt` under `evidenceDir('508')`). On this commit all
six pass (`uc-green.txt` there).
