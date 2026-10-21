# Workflow node coverage

Status: current (2026-10-19). Which seeded workflow runs each node type, and which use-case check proves it ran and
left by the expected port. Two ordinary bank workflows cover every node type a person adds on the canvas:
`customer_hold` (uc-248) and `complaint_triage` with its child `attachment_record` (uc-249). Both are configuration in
`services/agents-service/seed/engine_workflows.json`. Neither has a code path of its own.

Run both with the fake model:

```
make db-up ISOLATED=1
make usecase-test UC=uc-248 LAYER=ui ISOLATED=1
make usecase-test UC=uc-249 LAYER=ui ISOLATED=1
```

## Coverage

| Node type | Step (workflow) | Use-case check | Ports proved |
|---|---|---|---|
| Request (`ops.trigger.request`) | Hold requested (`customer_hold`); File to record (`attachment_record`) | uc-248 #1; uc-249 #2 | payload |
| Email received (`ops.trigger.email`) | Complaint received (`complaint_triage`) | uc-249 #1 | payload |
| Set fields (`ops.data.set`) | The account to hold (`customer_hold`); Urgent (`complaint_triage`) | uc-248 #1; uc-249 #1 | out |
| Match (`ops.data.match`) | Is it them? (`customer_hold`): name, plus last four or email | uc-248 #1, #3; uc-249 #4 (by email) | matched, none |
| If (`ops.flow.if`) | Anything to hold? (`customer_hold`); Did they quote a case?, Do they ask for a hold? (`complaint_triage`) | uc-248 #1, #4; uc-249 #1 | true, false |
| Switch (`ops.flow.switch`) | What came in, By urgency (`complaint_triage`) | uc-249 #1; uc-249 non-vacuous run (`otherwise`) | named cases, otherwise |
| Combine (`ops.data.combine`) | Put the facts together (`complaint_triage`) | uc-249 #1 | out |
| Join (`ops.flow.join`) | Meet (`uc400_branches`): limits and screening branches | uc-400 #1, #2 | out |
| Call a tool, read (`ops.action.tool`) | Look up the customer, Their accounts (`customer_hold`) | uc-248 #1 | ok |
| Call a tool, write under approval (`ops.action.tool`) | Place the hold (`customer_hold`, two approvers with step-up); Reply to the customer (`complaint_triage`) | uc-248 #2, #5; uc-249 #5 | ok |
| Call a tool, outside system (`ops.action.tool`) | Tell the outside system: `notify_webhook` (`customer_hold`) | uc-248 #2 (payload read back from the stand-in) | ok |
| Agent with an output schema (`ops.ai.agent`) | Triage the complaint, `ag_dispute` (`complaint_triage`) | uc-249 #1, #3 | ok |
| Extract with fields (`ops.ai.extract`) | Read the complaint (`complaint_triage`) | uc-249 #1 | ok |
| Extract with Detect (`ops.ai.extract`) | Recognise and read it (`attachment_record`) | uc-249 #2 (type `payment_receipt`) | ok |
| Human review with a deadline (`ops.flow.humanReview`) | Approve the hold, 4 hours, expires (`customer_hold`) | uc-248 #2 (approve), #5 (timeout) | approve, timeout |
| Human review (`ops.flow.humanReview`) | A supervisor decides (`customer_hold`); Approve the reply (`complaint_triage`) | uc-248 #5; uc-249 #5 | approve |
| Run workflow once (`ops.action.workflow`) | Start a hold (`complaint_triage` → `customer_hold`) | uc-249 #4 (the child waits at its review) | started |
| Run workflow for each (`ops.action.workflow`) | Record each attachment (`complaint_triage` → `attachment_record`) | uc-249 #2 | started |
| Run workflow for each and wait (`ops.action.workflow`) | Read each file two at a time (`uc402_letter` → `uc402_read_one`) | uc-402 #1, #2 (one child fails, listed) | done |
| Wait for a duration (`ops.flow.wait`) | Pause two seconds (`uc403_pause`) | uc-403 #1 | out |
| Wait until a date (`ops.flow.wait`) | Until the response date (`uc403_due`): past, not a date | uc-403 #2 | out, error |
| Human review with reminders (`ops.flow.humanReview`) | The court order check, `Check the levy` (`uc403_remind`) | uc-403 #3, #4 | approve |
| Open case (`ops.action.openCase`) | Open a case (`customer_hold`, `complaint_triage`, priority from the triage) | uc-248 #2; uc-249 #3 | opened |
| Add to case (`ops.action.addToCase`) | Note the hold on the case (`customer_hold`) | uc-248 #2, #5 | added |
| Save data on file (`ops.files.setData`) | Keep the read on the file (`attachment_record`) | uc-249 #2 | ok |
| Calculate (`ops.data.compute`) | Work out the hold: `min` of the asked amount and the balance (`customer_hold`) | uc-248 #1 (hold 2000) | out |
| End (`ops.flow.end`) | Every outcome below; Could not finish marked as a failure (`attachment_record`) | uc-248 #2–#5; uc-249 #2, #5, #7 (the run reads failed) | — |

Outcomes proved: `held`, `customer_not_found`, `nothing_to_hold` (uc-248); `recorded`, `replied`, `failed` (uc-249).
A parent waiting on the run it started, then succeeding when that run ends: uc-249 #5 and #6.

## On the shared stack with the real model

Run once each on 2026-10-19, with the same step paths as the isolated runs:

| Run | Workflow | Outcome |
|---|---|---|
| `wfrun_1578bdad3f3d` | `customer_hold`, started by request | `held`; case opened, hold noted, webhook sent |
| `wfrun_3d72d0968cf5` | `complaint_triage`, started by an email to `complaints@harborpine.test` | `replied`; the agent answered urgency `high`, case `case_f66d03aaa0d3` opened at `urgent` |
| `wfrun_77de8856f47a` | `attachment_record`, one per attachment | `recorded`; the receipt was recognised as `payment_receipt` |
| `wfrun_633f15328761` | `customer_hold`, started by the complaint | waits at Approve the hold, as intended |

## Not covered here

| Node type | Why | Where it runs |
|---|---|---|
| Event (`ops.trigger.event`) | Starts the handler a service event names; not added on the canvas | `seed/event_workflows.json`, `tests/api/test_service_events.py` |
| Purge read data (`ops.documents.purge`) | Runs only in the file-deleted event handler | `file_deleted_purge` in `seed/event_workflows.json` |

Ports not driven by these use cases: every node's `error` port, Call a tool's `refused`, Extract's `review` and
`unreadable`, and Human review's `reject`. The engine's own tests cover them (`packages/ops_engine/tests/`).

## What changed to make these run

Open case's priority accepts a path as well as a fixed value, checked when the step runs (`priority_invalid` on the
error port for anything else), so a triage step can set it. Test:
`packages/ops_engine/tests/test_switch_combine.py::test_open_case_takes_a_priority_worked_out_earlier_and_refuses_one_it_does_not_know`.
