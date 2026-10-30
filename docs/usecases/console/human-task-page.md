# A Human Task opens as its own page

Status: current. Id: `uc-234`. Service: `console` on agents-service, files-service and documents-service. Layers: ui.
Card: an earlier change.

A person deciding a Human Task needs the question, the evidence for it and the decision on one screen, with nothing
covering what they read. The task opens as a page with a header (the question), a body that is the only scroll area,
and a footer row that holds the decision. With a document, the document sits beside the values read from it from
1024px; below that one pane shows at a time. The queue's quick view stays, wider, with Open to reach the page. Design:
the Human Task redesign (planning notes, outside this repo), version 2, wireframes A to C (D is checked in
uc-224).

## Preconditions

| Needs | How |
|---|---|
| TEST012.pdf in Operations and the Restraining notice type | the stack's document-types seed |
| A read that waits for a check | the demo's fake model rule for `SYN-2026-0012`, which leaves the garnishee off the page |
| A worker for the system extract workflow, and Maya to decide | `stack.startWorker()`; the platform seed |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James reads TEST012.pdf with the Restraining notice type; Maya clicks the waiting task in Human Tasks, then goes back and uses the row's Quick view | The row opens `/reviews/<id>`; Quick view opens the side view (wider than the old 672px sheet) without leaving the list, and its Open goes to the page |
| 2 | She reads the page at 1280 | PageLayout's title asks "Check N fields read from TEST012.pdf"; the PDF is on the left with boxes over the values, the fields on the right, the garnishee marked Check |
| 3 | She looks for workflow and policy words, then opens Details | None of gate, step, run id or team id shows outside Details; Details starts folded and names the run |
| 4 | She scrolls the body to the end | The footer is a row below the body, never over it; it says what Approve does |
| 5 | At 400px she opens the same task | Evidence shows first; Decide switches to the fields; nothing scrolls sideways |
| 6 | She presses Approve in the footer | The run resumes and ends saved |
| 7 | James publishes a version of the type marking the case number and court as key fields and reads the file again; Maya opens the task | The title asks to check 2 key fields; they come first, each with Confirm; Approve says "confirm 2 key fields first" until both are confirmed; the other fields are folded under "Accept all" and say how many need a check; Approve saves the read |
| 8 | James asks for a workflow's access to Core banking; whoever the server says may decide opens the task at 1280 and 400 | The title is the request's own name with "approve or reject?"; the footer offers Approve and Reject; nothing scrolls sideways at 400 |
| 9 | A workflow reads TEST012.pdf, combines its case number with the one the request gave (SYN-2026-0099), and asks a person | The read check has a column per source (document, request); the case number shows both values and is marked Differs; a field the sources agree on is not marked |
| 10 | James opens a typed task over the API (write_approval: a bank account change with its facts and the call); Maya opens it, hovers Decline, presses it, gives a reason and presses it again | The question, why it waits, the facts and what it changes are the type's regions as the server bound them; the footer has the type's own buttons, Make the change and Decline, each with its consequence; Decline asks for a reason first, and the caller reads the decline and its reason back |
| 11 | Priya turns task assist on; James opens a typed task; Maya opens it | The AI assist comes first, labelled as AI, with its summary, the fields worth checking and its suggestion; the suggested button is marked and nothing is chosen or sent for her |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-234-ui.mjs` | passing |
