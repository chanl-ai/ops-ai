# A complaint email is triaged

Status: passing (2026-10-19). Id: `uc-249`. Service: `agents-service`. Layers: ui. One of the two workflows that
between them run every node type (`docs/services/agents-service/workflow-node-coverage.md`).

A customer emails the complaints mailbox with a receipt attached. `complaint_triage` records each attachment in its own
run of `attachment_record` (the file is recognised as one of the team's document types, read, and the read kept on the
file). It reads the complaint from the email text, puts the facts together, and asks an agent for a structured triage:
urgency, category, and whether the customer asks for a hold. The urgency sets the case priority. With no case quoted a
case opens. A requested hold starts `customer_hold` for the sender, and the customer gets a reply once the mail
module's team approves it. Real mail both ways. Nothing is faked but the bank and the model.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL, OPA, GreenMail and Mailpit for the isolated stack | `make db-up ISOLATED=1` |
| The run | `make usecase-test UC=uc-249 LAYER=ui ISOLATED=1` |

The stack is the banker demo with the seeded mailboxes (`complaints@harborpine.test` for `complaint_triage`) and
GreenMail and Mailpit reachable through tools-service (`tools.mail`). The `payment_receipt` document type is
configuration that the use case makes through the documents API.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | Sam stores the mailbox secret and allows the mail hosts; James adds the `payment_receipt` type | 201 for each |
| 1 | Marcus Bell emails a complaint with `receipt.pdf` attached | Email received (`mail:payload`), What came in (`what:attachments`), Record each attachment (`each:started`), Read the complaint (`read_body:ok`), Put the facts together (`combine:out`), Triage the complaint (`triage:ok`), By urgency (`urgency:high`), Urgent (`urgent:out`), Did they quote a case? (`has_case:false`), Open a case (`open:opened`), Do they ask for a hold? (`wants_hold:true`), Start a hold (`hold_once:started`); it waits at Approve the reply |
| 2 | The attachment's run | `attachment_record` ends `recorded`: Recognise and read it (`read:ok`, type `payment_receipt`), Keep the read on the file (`save:ok`) |
| 3 | The triage and the case | The agent answers urgency `high` and a hold asked; the case has priority `urgent` and the triage's category |
| 4 | The hold it started | `customer_hold` matched the customer by the sender's address (no SSN given), worked out 2000, and waits at Approve the hold |
| 5 | Wanjiru approves the reply | Reply to the customer (`reply:ok`), outcome `replied`, one more reply from `complaints@harborpine.test` in Mailpit; the run reads `waiting` with no finish time, because the hold it started still waits |
| 6 | James opens the complaint's run page, then Maya and Priya approve the hold, each re-authenticating | The page says "Waiting on a run it started"; the hold ends `held` and the complaint run then reads `succeeded` |
| 7 | `attachment_record` on a file that does not exist | `read:error`, the End Could not finish (marked failed): the run reads `failed` in the list with "Ended at Could not finish, an end marked as a failure", its page shows The run failed and the Result, and the editor shows the End's Counts as setting as `failed` |
| 8 | Activity filtered to the complaint's case (`GET /v1/activity?case=`) | The case's own entries, the complaint run, the email that started it and the reply's decision; nothing of the hold's run |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `agents-service/scripts/test-uc-249-ui.mjs` | passing |

## Non-vacuous check

With the fake agent's answer changed to urgency `low`, steps 1 and 3 fail: the run leaves By urgency by `otherwise`
and the case opens at priority `low`. The engine tests behind steps 5 to 7 fail with the run-status logic reverted:
a parent waiting on its child and a failure End both read `succeeded` (`tests/engine/test_start_workflow.py`).

## What this does not cover

A complaint that quotes an existing case (`has_case:true`, Add to case) is not sent; uc-248 runs Add to case. The
body-only path (an email with no attachment) is not sent.
