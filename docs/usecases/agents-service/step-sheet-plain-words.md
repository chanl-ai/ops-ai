# A builder reads a workflow step in plain words and picks values from earlier steps by name

Status: current. Id: `uc-512`. Service: `agents-service`. Layers: api, sdk, ui.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | The sample route lists each earlier step's fields with the acting team's last run values, masked, from the working copy | api | 1-3 | 2 |
| S2 | Through the Python SDK James reads the same sample; a viewer reads it and a member without the workflows view cell is refused | sdk | 4-5 | 5 |
| S3 | James opens a step and reads it in plain words: what it does, what it receives, its settings, when it fails, what it gives | ui | 6-8 | 7 |
| S4 | James picks a field by name and the next run's step receives the picked value | ui | 9-10 | 10 |
| S5 | Every state of the sheet: loading, error with Retry while Settings stays usable, no run yet, first step, not installed, viewer, picker no match and loading, Fix, Missing step | ui | 11-19 | 17 |
| S6 | An Email received trigger with a problem reads Problems, How it starts, Settings, in plain words at both widths | ui | 18 | 18 |
| S7 | Every installed step type opened with every list open shows only plain words: step names, operators and hints, never a type id, path, port or schema word; problems name the step and Fix never lands on Name | ui | 20-22 | 20 |

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
| 7 | Scan Done's and the Request trigger's text, at 1440 and 390 | No type id, `$.` path, "Effects:", run call, agent tool name or "input schema"; neither the page nor the sheet scrolls sideways |
| 8 | Open the trigger step; open Technical details | How it starts sits above Settings; the run call and tool name show only there |
| 9 | In Done's Output, Use a field…, search "zzz", then "amou", pick Fields → Amount | "Nothing matches."; then the chip "Fields → Amount" |
| 10 | Publish the copy and run it | The run's output is 42, read through the picked path |
| 11 | Open a step while the sample is slow | Skeleton rows under What it receives |
| 12 | Open a step while the sample fails; open the picker | What it receives, What it gives and the picker each show the error with Retry; the Name field stays editable |
| 13 | Open a step of a workflow that never ran | "No run yet" |
| 11b | Open the picker on a step while the sample is slow | Skeleton rows in the picker |
| 14 | Open a step nothing connects to | "This is the first step" |
| 15 | Open a step whose type is not installed | "This step's type is not installed"; settings read-only |
| 16 | Ravi opens a step, at 1440 and 390 | No Delete, no field picker, fields disabled; no sideways scroll |
| 17 | Open a Call a tool step with no operation; Fix | The operation field is focused |
| 18 | Open an Email received trigger whose daily cap is 0 | Problems, then How it starts, then Settings; no code words; no sideways scroll at 1440 or 390 |
| 19 | Open a Done step whose output reads a step that is gone | The chip says Missing step |
| 20 | Open one step of every installed type, open every list and the field picker on each, and press every Fix | No type id, `$.` path, port, schema or operator code word anywhere; no problem names a step by its id; no Fix lands on Name |
| 21 | Open Human review's Approves, Call a tool's Approved by and an If condition's operator list | Approves lists only the tool step by its name, Approved by only the review, and the operators read in words (Equal to, At least) |
| 22 | Open Human review and Classify | The review says it waits for a person, not that it gives up after seconds; Classify categories have no Authorises choice |
| 16b | Ravi double-clicks a step | The canvas keeps its zoom |

## Notes

The role grid has no separate right to view runs. The route asks `workflows.view`, then picks the run with the runs
list's own team rule and `visible_run`, so a shared workflow shows only the acting team's run
(`services/agents-service/tests/api/test_engine_sample.py`).

Scripts: `scripts/test-uc-512-api.py`, `scripts/test-uc-512-sdk.py`, `scripts/test-uc-512-ui.mjs`.
