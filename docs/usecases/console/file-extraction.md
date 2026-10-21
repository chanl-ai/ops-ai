# A file is read on its own page

Status: current. Id: `uc-227`. Service: `console` on files-service and documents-service. Layers: ui. Card: c-262.

A builder checks a document at file level before any workflow uses it: the file's own page shows its pages, Extract
reads it with a document type, and each field shows its value, confidence and the text it came from, with doubtful
fields marked. The Files list then says how each file was read. Design: `docs/services/documents-service/design.md`
screens 1 to 3.

## Preconditions

| Needs | How |
|---|---|
| TEST012.pdf (a synthetic restraining notice) in Operations, and the Restraining notice type | the stack's document-types seed |
| A model answer for it with one field not on the page | the demo's fake model rule for `SYN-2026-0012` |
| A worker for the system extract workflow, and Maya to approve its check | `stack.startWorker()`; the platform seed |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens Files and searches TEST012 | The row reads "Not read" under Read as; its name opens the file's page |
| 2 | He reads the Preview tab | The PDF shows in the viewer, with "Not read yet" and Extract beside it |
| 3 | He presses Extract, picks Restraining notice, Latest | A read request starts the system extract workflow as James; once it waits for the doubtful field's check, the dialog says so at the top of the screen and the page moves to Fields, linking that run; the case number reads SYN-2026-0012 with its quote, the garnishee, which is not on the page, is marked Check, and the issuing agency reads Not on the page with no confidence |
| 4 | Maya approves the check, and James goes back to Files | The run ends saved; Read as shows the type, version and path the workflow saved on the file |
| 5 | He opens Activity and Versions | Activity lists the read; Versions lists version 1 as current |
| 6 | At 400 px he opens the file's page | Nothing scrolls sideways |
| 7 | He goes back to Preview | Beside the PDF each field is one line with its quote under it (in full on hover); the garnishee is marked Check and the issuing agency reads Not on the page, with no confidence |
| 8 | He clicks the case number's box on the page, then the Court row | The case number's row is selected, then the Court box; the garnishee, not on the page, has no box |
| 9 | On Fields he presses Edit fields, types Northfield Bank Test Intake for the garnishee and saves | The read keeps his value, marked corrected, with "read as Northfield Bank" beside it, and it no longer waits for a check |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-227-ui.mjs` | passing |
