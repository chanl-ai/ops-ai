# Tool module details page

Status: current. Id: `uc-015`. Service: `tools-service`. Layers: ui.

The page is `/tools/[id]` in the console. Tool modules come from the console mock until tools-service serves
`/v1/tool-modules` behind `NEXT_PUBLIC_OPS_TOOLS_API_URL`; the script then runs unchanged against it.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` (the ui harness starts the scripted agents service too) |
| Free use-case ports | agents :8790, console :3018 (ISOLATED=1 adds 1000) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Open `/tools/mod_core_banking` at 1440 px | The test panel sits to the right of the tabs; there is no Test console tab |
| 2 | Run `get_loan_account` against the stub as the lending inbox case | Allowed, HTTP 200; the case binds the loan account |
| 3 | Pick `transfer_funds`, fill `toAccount` and `amount`, Run | Denied, HTTP 403, "The operation is hidden in this module." |
| 4 | Activity tab | Executions list each call with its caller and "via" the actor |
| 5 | Click a row's caller | The call sheet opens and names the same workflow |
| 6 | Resize to 375 px | No sideways scroll |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `tools-service/scripts/test-uc-015-ui.mjs` | passing |

## Non-vacuous check

`the test panel sits beside the Operations tab` failed with the panel's two-column grid removed (the panel dropped
below the tabs). `executions list a caller and who it acted via` failed with the "via" line removed from
`CallerCell`. Step 3's refusal pairs with step 2's allow on the same run context.
