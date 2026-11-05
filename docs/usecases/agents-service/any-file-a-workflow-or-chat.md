# Any file a workflow or chat reads ends read or with a reason

Status: draft. Id: `uc-620`. Service: `agents-service`. Layers: api, ui.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A builder's own workflow reads a notice with an Extract step and no save step, and Files says what it was read as | api | 1-2 | 1 |
| S2 | A notice sent through a hosted form finishes: with no mailbox it opens its cases and skips the reply; with a mailbox and no subject the acknowledgement opens with a default subject; a required field left empty is refused by the API as the console refuses it | api | 3-5 | 4 |
| S3 | A person attaches a PDF in chat and asks about it: the file goes to Files as a chat attachment, the agent answers from its text on the fake model and cites it, and a scan with no text is said plainly | api | 6-8 | 6 |
| S3 | The same in the console: the composer's attach uploads to Files, the reply answers from the file, the message links to the file in Files, and a type chat cannot read is refused in words on the chip | ui | 9-11 | 9 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| The demo's fake OpenAI, with the levy notice's extraction and the uc620 chat rule | `services/models-service/seed/demo-fake-openai/script.json`, through models-service |
| files-service and documents-service delivering events to this run's agents-service, and a workflow worker | started by the script |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Publish a workflow with Extract from file as `levy_notice` and no Save data on file step; start it with the notice | The run succeeds; the file's `data` names `levy_notice`, `Levy notice`, the fields to check and the extraction |
| 2 | List `extraction_read_save` runs | One ended `saved`: documents-service reported `extraction.read` |
| 3 | Share a team copy of `mail_document` as a form; submit the notice with a sender and no mailbox | The run ends `cases_opened` with a message naming no mailbox, sender or subject |
| 4 | Submit again with a mailbox and no subject | The run waits at the acknowledgement, whose reply has the subject "We received your document" |
| 5 | Submit with the file and sender empty; start by hand through the API with the sender empty | 422 `invalid_input` naming the empty required fields |
| 6 | Upload the notice as a chat attachment (ticket, bytes, complete); in a chat with an agent that has no knowledge bases, ask "uc620 who is the first debtor in this notice?" with the file attached | The reply names Marcus Bell and 3,250.00 and cites the file's id on page 1 |
| 7 | List Files' chat attachments; delete the file in Files; ask "uc620 what did I attach?" | The file is listed as `chat_attachment`; the delete answers 204; the reply says the file could not be read because it is no longer in Files |
| 8 | Attach a scan with no text layer and ask about it | The reply ends "scan-….pdf could not be read: it has no text to read" |
| 9 | In the console, attach the notice in the composer and send the same question | The upload goes through Files' ticket routes; the reply shows "is Marcus Bell, held for 3,250.00"; the message carries a `fil_` id |
| 10 | Click the attachment on the message | Files opens the file, shown as a Chat attachment |
| 11 | Attach a PNG | The chip says "PNG is not accepted here. Accepted: PDF, …" |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-620-api.py` | passing: S1, S2, S3 (8 of 8) |
| ui | `agents-service/scripts/test-uc-620-ui.mjs` | passing: S3 (3 of 3) |

## Non-vacuous check

On 8195ab8a plus the service changes but the old seeds, steps 1-4 failed: no data on the file, no
`extraction_read_save` run, the form refused an empty mailbox, and the acknowledgement failed with "Reply from the
mailbox has no subject to use from this run."

With the turn's attached passages withheld (`graph_input["attached_passages"]` not set), step 6 failed: the fake model
had no knowledge block to answer from and replied with its generic text.
