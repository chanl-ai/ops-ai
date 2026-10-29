# Start a run from a clear form

Status: current. Id: `uc-445`. Service: `console` on agents-service and files-service. Layers: ui. Card: c-445.

A person starts a workflow from the Workflows list without knowing a file id or a field key. Choosing a workflow opens
its form at once; each field is labelled by its schema `title` (else its key in words), a `oneOf` of `{ const, title }`
or an `enum` is a select, and a string field with `format: "file"` uploads a file or picks one from Files and sends the
bare id. The use case runs copies of the demo card dispute (`scripts/sample-team/workflows/card_dispute_intake.json`) and the
seeded `mail_document` notice workflow, read from those files at run time, so it checks the schemas the demo ships.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James presses Start run on the Workflows list and chooses the dispute copy | Its form opens with no other click; labels read Last four digits of SSN and Card type; Card type offers Debit card and Credit card |
| 1d | He fills the form, picks Debit card and starts a test run | The run's input has `cardType: "debit"` and `ssnLast4: "5555"` |
| 2 | He chooses the notice copy, uploads TEST012.pdf in Notice file and starts a test run | The field is an upload and a picker; the run's input `fileId` is the uploaded file's id as a string |
| 3 | He chooses the notice copy again and picks TEST012.pdf from Files | The run's input `fileId` is that file's id as a string |

`OPS_UC445_SHARED=1` runs the same steps on the local shared stack (console :3016) and saves screenshots under
the card's evidence folder, one subfolder per `OPS_UC445_PHASE`; the default is a private stack.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-445-ui.mjs` | passing |

## Non-vacuous check

Run on the code before the fix: 1a failed (the picker needed a second click),
1b saw "Ssn last4", 1c found Card type as free text, and 2a found a "File ID" text box with no picker.
