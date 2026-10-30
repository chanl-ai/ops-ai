# An email in a watched mailbox starts a workflow

Status: current. Id: `uc-150` (api), `uc-151` (ui). Service: `agents-service`. Layers: api, ui. Card: an earlier change.

A builder picks Email received as a workflow's trigger and points it at a team mailbox. Once the workflow is live,
the workflow worker reads the mailbox through `packages/ops_email`; each new message that matches the filters stores
its attachments in Files and starts one run whose input is the email.

## Preconditions

| Needs | How |
|---|---|
| The shared stack with platform sign-in | `OPS_STACK_AUTH=platform make up`; the dev seed (`services/agents-service/seed/mailboxes.json`) connects `levy@harborpine.example`, an IMAP mailbox on the stack's GreenMail, for team_ops |
| files-service | part of the stack; the worker writes attachments there as agents-service |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James asks for the mailbox options | `levy@harborpine.example` is offered |
| 2 | James saves a workflow whose trigger is Email received on that mailbox and publishes it | 201 and the workflow is live |
| 3 | The worker's first pass on the new binding | No run: mail already in the folder is history |
| 4 | The court order notice with its PDF is emailed to `levy@harborpine.example` through GreenMail's SMTP | One run; its input has the sender, subject, body and the PDF as a Files id, never its bytes |
| 5 | Read the file from files-service as James | The bytes are the PDF's |
| 6 | The same message again, with other brackets and domain case | No second run |
| 7 (ui) | James adds Email received on the canvas, picks the mailbox, sets a folder and filters, saves | The sheet says how it starts; the saved version keeps mailbox, folder and filters |

Who may bind a mailbox is `services/agents-service/tests/engine/test_email_trigger_binding.py`; the listener's
failure modes (history, redelivery, two workers, Files first, filters, pause, a new folder) are
`tests/engine/test_email_trigger.py`.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-150-api.py` | passing |
| ui | `console/scripts/test-uc-151-ui.mjs` | passing |

In the console: uc-245's ui script: a team's mailbox is connected and tested, an email's PDF starts one run with the PDF in Files, and a redelivery starts none.

## Non-vacuous check

Step 6 fails when the run key is not derived from the normalised Message-ID.
