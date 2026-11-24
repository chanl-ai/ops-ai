# A read no model reply answered goes to a person

Status: passing. Id: `uc-776`. Service: `documents-service`. Layers: api, ui.

Short title: A read no model reply answered goes to a person

## Story

As an accounts clerk, I want a file whose model reply was cut off or declined to wait for me with the reason, so that
I type the values it needs instead of finding empty fields on the file later.

## People

| Person | Role | Does what |
|---|---|---|
| Maya Okafor | member of Operations | Decides the Human Task: rejects it, or types the required fields and approves |
| The workspace admin | admin | Publishes the Extract a file workflow's versions (here through the API, as the update in Reviews does) |

## In this example

In this example a freight invoice is read with Detect from Files, and the model's reply to its extraction stops at the
output limit, twice. It assumes the workspace's defaults: one retry, then send to review. A second invoice's reply is
declined. The fake model answers what the fixtures expect, so this proves the chain, not the model.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | On a workspace still on the Extract from before typed values, a cut-off read waits for a person with the reason, approve is refused with `not_editable`, and the task can only be rejected | api | 1 | 1 |
| S2 | After the update goes live, the rejected file is read again from Files without uploading it, an empty approve is refused, and typed values are approved and saved on the file | api | 2 | 2 |
| S3 | The typed values are kept on the read with the person who typed them and no original value | api | 3 | 3 |
| S4 | A declined reply waits for a person as declined, with every field not read | api | 4 | 4 |
| S5 | The file's panel says why nothing was read, with the way to the task that waits for its values and a row in Activity that says it waits | ui | 5 | 5 |
| S6 | The task counts the required fields still to type, marks each field Required or Optional and Typed or Not read, and holds Confirm until none is left | ui | 6 | 6 |
| S7 | A person who may only view reads the reason and the task, and cannot type or decide | ui | 7 | 7 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL | `make db-up` |
| The fake OpenAI with the documents fixtures' rules and the two invoices' endings | written by the script from `services/documents-service/tests/fixtures/fake-model/script.json` |
| platform-service, the console and a workflow worker, on the run's own ports (ui layer) | started by the script (`withUiStack`) |
| files-service, documents-service with the seeded types, agents-service with the shipped `system_extract`, a worker | started by the script |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Read one fixture invoice from Files, publish the version of `system_extract` whose check takes no typed values, upload invoice INV-77201 and ask Files to read it; open its task, try to approve with typed values, then reject it | The task's read says `notRead: cut_off`, `editable: false` and `approveRefused.code: not_editable`; its line says "the reply was cut off"; approve answers 400 `not_editable`; the run ends `needs_manual_read` and the file has no read |
| 2 | Publish the shipped `system_extract` again (the update), ask Files to read the same file, approve with nothing typed, then with the invoice number, vendor and total typed and the key fields confirmed | The new task is editable with no refusal; the empty approve answers 400 `required_fields_empty`; the typed one ends `saved` and the file is a supplier invoice with no fields to check |
| 3 | Read the extraction from documents-service | One correction per typed field, each by Maya with original null; "1,940.00" is stored as 1940 |
| 4 | Upload invoice INV-77202 and ask Files to read it | Its task says `notRead: declined` and "the model declined"; every value is empty |
| 5 | Priya, an admin of Operations, opens the file's Fields tab, then its Activity tab | The panel says the reply stopped at its length limit and the one retry stopped too, that the values are typed in the task, and links to it; the Activity row says it waits in Human Tasks; nothing scrolls sideways at 1440 or 390 |
| 6 | She opens the task, then types the invoice number, vendor and total and confirms the key fields | The header says how many required fields are left to type, each row says Key field or Required and Not read, Confirm says to type the required fields first; once typed the count is gone and Confirm is live |
| 7 | Ravi, who may only view, opens the same file and task | The panel gives the reason and the way to the task, and the task shows the reason with no input and no Approve or Reject; nothing scrolls sideways at 1440 or 390 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `documents-service/scripts/test-uc-776-api.py` | passing: S1 to S4 (4 of 4) |
| ui | `documents-service/scripts/test-uc-776-ui.mjs` | passing: S5 to S7 (3 of 3) |

## Non-vacuous check

On the first run the update was saved through `POST /v1/workflows/definitions`, which returns the version already
stored for the same definition, so the old version stayed live: check 2 failed with approve answering 400
`not_editable` and check 3 found no corrections. Publishing through the working copy made the new version and both
passed.

The first ui run failed step 6: the task opened in the quick view, whose Approve ignored the hold and read "Approve"
with no field typed. The next failed on typing the vendor, a required field that was folded under "Other fields"
because the type marks another field key. The quick view now holds Approve and a not-read read opens every field;
the run then passed.

The refusal and the hold each have a unit test seen failing: `services/agents-service/tests/unit/test_review_document_read.py`
(no `approveRefused` on the read, KeyError) and `services/documents-service/tests/test_typed_corrections.py` (with the
hold edited out, a partly typed read sent its corrected event).
