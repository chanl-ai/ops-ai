# A person corrects a document read in Human Tasks and sees the reply and cases

Status: passing. Id: `uc-224`. Service: `agents-service`. Layers: ui. Card: an earlier change.

A mailed document is read into fields; a field below the floor stops the read at Check the read in Human Tasks. The
reviewer sees the file, each field's confidence and the page and quote it came from, corrects a misread value and
approves, and the debtor's court order case starts on the corrected value. The acknowledgement that follows shows the reply as
it will leave and the case run it follows.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The demo stack on the run's own ports, with a worker | the script's `withUiStack({ platform, demo })` and `startWorker` |
| A faxed notice the fake model misreads | `services/agents-service/tests/fixtures/mailbox/levy_notice_smudged.pdf`; the demo rule reads "Ana Example" as "Anna Exempel", with a quote not on the page |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James uploads the notice to Files and starts `mail_document` on it, as the mailbox trigger does per attachment | The run waits at `check` |
| 2 | Maya opens it in Human Tasks | The file's name links to Files; each field shows its value, confidence and page quote; only Name is marked Check, at 0% |
| 3 | She types "Ana Example" over the name and approves | The row shows Corrected, read as "Anna Exempel"; the decision sends the whole record with her name; the `levy_case` run's record name is "Ana Example" |
| 3b | The panel after her decision | It stays on the task she decided and says who decided it; it never moves to another task |
| 3c | James opens the run | Decisions lists Check the read: Approve by Maya Okafor, when, linked to the task |
| 4 | She opens the acknowledgement | To is the sender, From is the team mailbox, and the court order case run is listed |
| 4b | She opens the acknowledgement as its own page | The title asks whether to send the reply to the sender, and the reply shows beside the decision |
| 4c | The same notice for a debtor the bank has (Marcus Bell) waits at Hold or flag; she opens that task | The title asks one plain question naming both choices and the customer, the notice shows beside it, the footer is one row, and hovering an option says what it does; no tool name, raw key or raw float on the page |
| 4d | She opens the mailed document's run | It lists the court order case it started for the debtor, with its status and a link, and the canvas says the step runs for each debtor read |
| 5 | — | No page errors |
| 6 | A read naming three debtors waits for a check | The page shows one tab per debtor and one record at a time; at 1280 each record's table fits its pane with the source quote wrapped |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `agents-service/scripts/test-uc-224-ui.mjs` | passing, `ISOLATED=1 make usecase-test UC=uc-224 LAYER=ui` (2026-10-18) |

The row shapes (`read`, `reply`) are covered without a stack by `services/agents-service/tests/unit/test_review_document_read.py`.

## Non-vacuous check

With the reviews page sending no correction on Approve (2026-10-18), step 3 failed: the court order case started on
"Anna Exempel". With `read` and `reply` left off the review row, three of the four unit tests failed.
