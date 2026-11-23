# A builder reads a workflow step in plain words and picks values from earlier steps by name

Status: current. Id: `uc-512`. Service: `agents-service`. Layers: api, sdk, ui.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | The sample route lists each earlier step's fields with the acting team's last run values, masked, from the working copy | api | 1-3 | 2 |
| S2 | Through the Python SDK James reads the same sample; a viewer reads it and a member without the workflows view cell is refused | sdk | 4-5 | 5 |
| S3 | James opens a step and reads it in plain words: what it does, what it receives, its settings, when it fails, what it gives | ui | 6-8 | 7 |
| S4 | James picks a field by name and the next run's step receives the picked value | ui | 9-10 | 10 |
| S5 | Every state of the sheet: loading, error with Retry while Settings stays usable, no run yet, first step, not installed, viewer, picker no match, Fix | ui | 11-17 | 17 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA (docker) | `make db-up` |
| Free use-case ports | the runner picks free ports and a database of its own |

The scripts start agents-service (scripted model) and a workflow worker; the sdk and ui scripts add platform-service
for sign-in (James builds, Ravi views, Lena only chats) and the console. No model is called.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James saves and publishes Refund check; `GET …/sample?step=done` | No run; the trigger's and Fields' fields listed with paths |
| 2 | A worker runs it with amount 42 and a customer email; read the sample | Amount reads 42; the email is masked |
| 3 | Save a working copy with a new Note step; read the sample, and for a step the copy lacks | Note's field is listed; the unknown step says `saved: false` |
| 4 | James, through the SDK, `workflows_definition_sample` | The same fields and values |
| 5 | Ravi (viewer) and Lena (chat only) read it | Ravi 200; Lena 403 |
| 6 | James opens the Done step | The sheet shows the plain summary, What it receives with Fields' values, When it fails and What it gives |
| 7 | Scan the sheet's text, at 1440 and 390 | No type id, `$.` path or "Effects:"; no sideways scroll at either width |
| 8 | Open the trigger step | How it starts sits above Settings |
| 9 | In Done's Output, Use a field…, search "zzz", then "amount", pick Fields → Amount | "Nothing matches."; then the chip "Fields → Amount" |
| 10 | Publish the copy and run it | The run's output is 42, read through the picked path |
| 11 | Open a step while the sample is slow | Skeleton rows under What it receives |
| 12 | Open a step while the sample fails | Its own error with Retry; the Name field stays editable |
| 13 | Open a step of a workflow that never ran | "No run yet" |
| 14 | Open a step nothing connects to | "This is the first step" |
| 15 | Open a step whose type is not installed | "This step's type is not installed"; settings read-only |
| 16 | Ravi opens a step | No Delete, no field picker, fields disabled |
| 17 | Open a Call a tool step with no operation; Fix | The operation field is focused |

## Notes

The role grid has no separate right to view runs. The route asks `workflows.view`, then picks the run with the runs
list's own team rule and `visible_run`, so a shared workflow shows only the acting team's run
(`services/agents-service/tests/api/test_engine_sample.py`).

Scripts: `scripts/test-uc-512-api.py`, `scripts/test-uc-512-sdk.py`, `scripts/test-uc-512-ui.mjs`.
