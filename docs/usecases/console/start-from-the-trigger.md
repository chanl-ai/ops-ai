# Start a workflow from its trigger's start form

Status: current. Id: `uc-466`. Service: `console` on agents-service and files-service. Layers: ui. Card: c-466.

A person starts any workflow from one dialog drawn from the start form its trigger declares, and never types a file id.
An Email received trigger declares "Send a test email" (From, Subject, Body, Attachments): the email goes through the
same start the mailbox listener uses, so the run gets the input a mailbox email gives and takes the same steps. Files
offers "Start a workflow with this file" on each file, listing only workflows a file can start. A workflow whose
Request trigger has "Only other workflows start this" on is offered by neither picker. The use case runs copies of the
seeded court order notice workflows (`mail_intake`, `mail_document`, `levy_case` in
`services/agents-service/seed/engine_workflows.json`) on the demo stack with a worker.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James presses Start run on the Workflows list and searches uc-466 | The email intake copy is offered; the read and the debtor copies, started only by other workflows, are not |
| 2 | He chooses the intake, picks Test run, writes the email and attaches `levy_notice.pdf`, then sends it | Send a test email shows From, Subject, Body and Attachments and no file id box; the run's input has exactly the EMAIL keys, the notice as an Email attachment file and the text as `email-body.txt`; it reads as sent by James as a test email, and the notice reaches a Human Task |
| 3 | In Files he opens the notice's menu and chooses Start a workflow with this file | Only the intake is offered; its test email opens with the notice attached |
| 5 | He uploads the same PDF again with purpose Chat attachment | The upload reuses the stored file ("Already stored in your team · reused") |

`UC466_ONLY=5` runs step 5 alone. Screenshots are saved with the card's evidence.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-466-ui.mjs` | passing |

## Non-vacuous check

Step 5 run on the console without the upload fix (purposes other than knowledge and email attachment uploaded to the
in-browser mock) failed: the upload ended in "File was not found". The service-side failure modes are proven red, then
green, by `services/agents-service/tests/engine/test_run_starts.py`, `tests/api/test_workflow_start_kind.py` and
`packages/ops_engine/tests/test_starts.py`; their output is in the card's evidence folder.
