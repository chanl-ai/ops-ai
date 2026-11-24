# A read no model reply answered goes to a person

Status: passing. Id: `uc-772`. Service: `documents-service`. Layers: api.

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
| S1 | On a workspace still on the Extract from before typed values, a cut-off read waits for a person with the reason, approve is refused with `not_editable`, and the task can only be rejected | api | 1-2 | 1 |
| S2 | After the update goes live, the rejected file is read again from Files without uploading it, an empty approve is refused, and typed values are approved and saved on the file | api | 3-4 | 2 |
| S3 | The typed values are kept on the read with the person who typed them and no original value | api | 5 | 3 |
| S4 | A declined reply waits for a person as declined, with every field not read | api | 6 | 4 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL | `make db-up` |
| The fake OpenAI with the documents fixtures' rules and the two invoices' endings | written by the script from `services/documents-service/tests/fixtures/fake-model/script.json` |
| files-service, documents-service with the seeded types, agents-service with the shipped `system_extract`, a worker | started by the script |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Read one fixture invoice from Files, then publish the version of `system_extract` whose check takes no typed values | The read saves; the older version is live |
| 2 | Upload invoice INV-77201 and ask Files to read it; open its task; approve with typed values; reject it | The task's read says `notRead: cut_off`, `editable: false` and `approveRefused.code: not_editable`; its line says "the reply was cut off"; approve answers 400 `not_editable`; the run ends `needs_manual_read` and the file has no read |
| 3 | Publish the shipped `system_extract` again (the update) and ask Files to read the same file | The new task is editable and has no refusal |
| 4 | Approve with nothing typed; then with the invoice number, vendor and total typed and the key fields confirmed | 400 `required_fields_empty`; then the run ends `saved` and the file is a supplier invoice with no fields to check |
| 5 | Read the extraction from documents-service | One correction per typed field, each by Maya with original null; "1,940.00" is stored as 1940 |
| 6 | Upload invoice INV-77202 and ask Files to read it | Its task says `notRead: declined` and "the model declined"; every value is empty |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `documents-service/scripts/test-uc-772-api.py` | passing: S1 to S4 (4 of 4) |

## Non-vacuous check

The refusal and the hold each have a unit test seen failing: `services/agents-service/tests/unit/test_review_document_read.py`
(no `approveRefused` on the read, KeyError) and `services/documents-service/tests/test_typed_corrections.py` (with the
hold edited out, a partly typed read sent its corrected event).
