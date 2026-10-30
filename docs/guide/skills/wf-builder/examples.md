# /wf-builder examples

Status: current. Generated from `services/agents-service/seed/engine_workflows.json` by
`scripts/wf_builder_examples.py`; change the seeds, then run it. `make docs-verify` fails on a stale page.

Each example is a seeded workflow a dev stack starts with. Name one as `example` in a goal file and
`scripts/wf_builder.py create` adapts it.

## customer_summary

Customer summary. Summarise a customer for a banker: the bank finds the customer by name and reads their record, and the advisor agent summarises that record with the customer id.

| Step | Type |
|---|---|
| Request (`start`) | `ops.trigger.request` |
| Find the customer (`find`) | `ops.action.tool` |
| Found? (`found`) | `ops.flow.if` |
| Read the record (`read`) | `ops.action.tool` |
| Summarise the customer (`summarise`) | `ops.ai.agent` |
| Summarised (`done`) | `ops.flow.end` |
| No summary (`failed`) | `ops.flow.end` |
| Not found (`not_found`) | `ops.flow.end` |

| From | Port | To |
|---|---|---|
| `start` | payload | `find` |
| `find` | ok | `found` |
| `find` | refused | `not_found` |
| `find` | error | `not_found` |
| `found` | true | `read` |
| `found` | false | `not_found` |
| `read` | ok | `summarise` |
| `read` | refused | `not_found` |
| `read` | error | `not_found` |
| `summarise` | ok | `done` |
| `summarise` | error | `failed` |

## levy_case

Levy case. One debtor of a garnishment notice: find the customer by name and address or the last four, then a reviewer holds funds or flags the customer; a debtor who matches no customer goes to a person to find or close.

| Step | Type |
|---|---|
| Debtor (`start`) | `ops.trigger.request` |
| Search customers (`search`) | `ops.action.tool` |
| Match the debtor (`match`) | `ops.data.match` |
| Open the levy case (`case`) | `ops.action.openCase` |
| Open a No customer matched case (`case_unmatched`) | `ops.action.openCase` |
| Find the customer or close as not ours (`find`) | `ops.flow.humanReview` |
| Customer found by a person (`found_by_person`) | `ops.flow.end` |
| Closed as not ours (`not_ours`) | `ops.flow.end` |
| List accounts (`accounts`) | `ops.action.tool` |
| Record the accounts on the case (`record_accounts`) | `ops.action.addToCase` |
| Hold or flag (`review`) | `ops.flow.humanReview` |
| Place the hold (`hold`) | `ops.action.tool` |
| Note the customer (`flag`) | `ops.action.tool` |
| Held (`held`) | `ops.flow.end` |
| Flagged (`flagged`) | `ops.flow.end` |
| Lookup failed (`lookup_failed`) | `ops.flow.end` |
| Case not opened (`case_failed`) | `ops.flow.end` |

| From | Port | To |
|---|---|---|
| `start` | payload | `search` |
| `search` | ok | `match` |
| `search` | refused | `lookup_failed` |
| `search` | error | `lookup_failed` |
| `match` | matched | `case` |
| `match` | none | `case_unmatched` |
| `accounts` | ok | `record_accounts` |
| `accounts` | refused | `lookup_failed` |
| `accounts` | error | `lookup_failed` |
| `review` | hold | `hold` |
| `review` | flag | `flag` |
| `hold` | ok | `held` |
| `hold` | refused | `review` |
| `hold` | error | `review` |
| `flag` | ok | `flagged` |
| `flag` | refused | `review` |
| `flag` | error | `review` |
| `case` | opened | `accounts` |
| `case` | error | `case_failed` |
| `case_unmatched` | opened | `find` |
| `case_unmatched` | error | `case_failed` |
| `record_accounts` | added | `review` |
| `record_accounts` | error | `review` |
| `find` | found | `found_by_person` |
| `find` | not_ours | `not_ours` |

## levy_intake

Levy intake. A garnishment notice in the levy mailbox: read each debtor from its PDF and open a levy case per debtor.

| Step | Type |
|---|---|
| Notice received (`mail`) | `ops.trigger.email` |
| Read the debtors (`read`) | `ops.ai.extract` |
| Any debtors (`any`) | `ops.flow.if` |
| Open a case per debtor (`open`) | `ops.action.workflow` |
| Cases opened (`opened`) | `ops.flow.end` |
| Needs a manual read (`manual`) | `ops.flow.end` |
| Not opened (`failed`) | `ops.flow.end` |
| Save what was read (`save`) | `ops.files.setData` |

| From | Port | To |
|---|---|---|
| `mail` | payload | `read` |
| `read` | ok | `save` |
| `read` | review | `save` |
| `read` | unreadable | `manual` |
| `read` | error | `manual` |
| `any` | true | `open` |
| `any` | false | `manual` |
| `open` | started | `opened` |
| `open` | error | `failed` |
| `save` | ok | `any` |
| `save` | error | `any` |

## mail_document

Mailed document. One emailed document: read every debtor it names, a person checks a read below the floor, a levy case opens per debtor, and the sender gets an acknowledgement from the mailbox once a reviewer approves it.

| Step | Type |
|---|---|
| Document (`start`) | `ops.trigger.request` |
| Read the debtors (`read`) | `ops.ai.extract` |
| Check the read (`check`) | `ops.flow.humanReview` |
| Open a case per debtor (`open`) | `ops.action.workflow` |
| No mailbox or sender? (`reply_check`) | `ops.flow.if` |
| Send the acknowledgement (`ack`) | `ops.flow.humanReview` |
| Reply from the mailbox (`reply`) | `ops.action.tool` |
| Replied (`replied`) | `ops.flow.end` |
| No reply (`no_reply`) | `ops.flow.end` |
| Reply not sent (`reply_failed`) | `ops.flow.end` |
| Needs a manual read (`manual`) | `ops.flow.end` |
| Cases not opened (`not_opened`) | `ops.flow.end` |
| Save what was read (`save`) | `ops.files.setData` |
| Save what was read (`save_for_check`) | `ops.files.setData` |
| Nothing to reply to (`nothing_to_reply`) | `ops.flow.end` |

| From | Port | To |
|---|---|---|
| `start` | payload | `read` |
| `read` | ok | `save` |
| `read` | review | `save_for_check` |
| `read` | unreadable | `manual` |
| `read` | error | `manual` |
| `check` | approve | `open` |
| `check` | reject | `manual` |
| `open` | started | `reply_check` |
| `open` | error | `not_opened` |
| `reply_check` | true | `nothing_to_reply` |
| `reply_check` | false | `ack` |
| `ack` | approve | `reply` |
| `ack` | reject | `no_reply` |
| `reply` | ok | `replied` |
| `reply` | refused | `reply_failed` |
| `reply` | error | `reply_failed` |
| `save` | ok | `open` |
| `save` | error | `open` |
| `save_for_check` | ok | `check` |
| `save_for_check` | error | `check` |

## mail_intake

Mailed documents. Documents emailed to the intake mailbox: each attachment is read in its own run; files-service's limits decide what is stored, and the run lists what was skipped.

| Step | Type |
|---|---|
| Document received (`mail`) | `ops.trigger.email` |
| Read each attachment (`each`) | `ops.action.workflow` |
| Documents read (`done`) | `ops.flow.end` |
| Not read (`failed`) | `ops.flow.end` |

| From | Port | To |
|---|---|---|
| `mail` | payload | `each` |
| `each` | started | `done` |
| `each` | error | `failed` |

## levy_read_one

Read one levy document. One document of a levy email: its kind is detected, a doubtful read goes to a person, each kind is worked out and opens a case (a levy notice, one per person it names), and the outside system is told by webhook. Unknown kinds go to a person.

| Step | Type |
|---|---|
| Document to read (`start`) | `ops.trigger.request` |
| Detect the kind and read it (`read`) | `ops.ai.extract` |
| Check the read (`check`) | `ops.flow.humanReview` |
| The fields to use (`facts`) | `ops.data.set` |
| By kind (`kind`) | `ops.flow.switch` |
| A person decides (`person`) | `ops.flow.humanReview` |
| Work out the response date (`notice_terms`) | `ops.data.compute` |
| Work out the levy (`levy_terms`) | `ops.data.compute` |
| Open a restraining notice case (`notice_case`) | `ops.action.openCase` |
| Open a tax levy case (`levy_case`) | `ops.action.openCase` |
| Notify the outside system (`notify_notice`) | `ops.action.tool` |
| Notify the outside system (`notify_levy`) | `ops.action.tool` |
| Restraining notice handled (`notice_done`) | `ops.flow.end` |
| Tax levy handled (`levy_done`) | `ops.flow.end` |
| A case per person named (`notices`) | `ops.action.workflow` |
| Levy notice handled (`notices_done`) | `ops.flow.end` |
| Handled by a person (`for_a_person`) | `ops.flow.end` |
| Could not finish (`failed`) | `ops.flow.end` |
| Save what was read (`save`) | `ops.files.setData` |
| Save what was read (`save_for_check`) | `ops.files.setData` |

| From | Port | To |
|---|---|---|
| `start` | payload | `read` |
| `read` | ok | `save` |
| `read` | review | `save_for_check` |
| `read` | unreadable | `person` |
| `read` | error | `failed` |
| `check` | approve | `facts` |
| `check` | reject | `person` |
| `facts` | out | `kind` |
| `kind` | restraining_notice | `notice_terms` |
| `kind` | tax_levy | `levy_terms` |
| `kind` | levy_notice | `notices` |
| `notices` | started | `notices_done` |
| `notices` | error | `failed` |
| `kind` | otherwise | `person` |
| `person` | approve | `for_a_person` |
| `person` | reject | `for_a_person` |
| `notice_terms` | out | `notice_case` |
| `notice_terms` | error | `notice_case` |
| `levy_terms` | out | `levy_case` |
| `levy_terms` | error | `levy_case` |
| `notice_case` | opened | `notify_notice` |
| `notice_case` | error | `failed` |
| `levy_case` | opened | `notify_levy` |
| `levy_case` | error | `failed` |
| `notify_notice` | ok | `notice_done` |
| `notify_notice` | refused | `failed` |
| `notify_notice` | error | `failed` |
| `notify_levy` | ok | `levy_done` |
| `notify_levy` | refused | `failed` |
| `notify_levy` | error | `failed` |
| `save` | ok | `facts` |
| `save` | error | `facts` |
| `save_for_check` | ok | `check` |
| `save_for_check` | error | `check` |

## levy_mail

Levy mail, mixed kinds. An email carrying levy documents of different kinds: each attachment is read in its own run, in parallel, and the sender gets a reply once a person acknowledges it.

| Step | Type |
|---|---|
| Levy email received (`mail`) | `ops.trigger.email` |
| What came in (`what`) | `ops.flow.switch` |
| Read each document (`each`) | `ops.action.workflow` |
| Read the email text (`body`) | `ops.action.workflow` |
| No mailbox or sender? (`reply_check`) | `ops.flow.if` |
| Acknowledge the email (`ack`) | `ops.flow.humanReview` |
| Reply to the sender (`reply`) | `ops.action.tool` |
| Replied (`replied`) | `ops.flow.end` |
| Not replied (`no_reply`) | `ops.flow.end` |
| Nothing to read (`unreadable`) | `ops.flow.end` |
| Could not finish (`failed`) | `ops.flow.end` |
| Nothing to reply to (`nothing_to_reply`) | `ops.flow.end` |

| From | Port | To |
|---|---|---|
| `mail` | payload | `what` |
| `what` | attachments | `each` |
| `what` | body_only | `body` |
| `what` | otherwise | `unreadable` |
| `each` | started | `reply_check` |
| `each` | error | `failed` |
| `body` | started | `reply_check` |
| `body` | error | `failed` |
| `reply_check` | true | `nothing_to_reply` |
| `reply_check` | false | `ack` |
| `ack` | approve | `reply` |
| `ack` | reject | `no_reply` |
| `reply` | ok | `replied` |
| `reply` | refused | `failed` |
| `reply` | error | `failed` |

## levy_files

Levy documents, run with files. The same per-document handling as Levy mail, started from files uploaded in the console.

| Step | Type |
|---|---|
| Files to read (`start`) | `ops.trigger.request` |
| Read each document (`each`) | `ops.action.workflow` |
| Each document started (`started`) | `ops.flow.end` |
| Could not start (`failed`) | `ops.flow.end` |

| From | Port | To |
|---|---|---|
| `start` | payload | `each` |
| `each` | started | `started` |
| `each` | error | `failed` |

## customer_hold

Hold on a customer's account. Finds the customer, works out how much can be held, and holds it once a person approves within four hours, or a supervisor after that; the hold opens a case and tells the outside system.

| Step | Type |
|---|---|
| Hold requested (`start`) | `ops.trigger.request` |
| Look up the customer (`search`) | `ops.action.tool` |
| Is it them? (`match`) | `ops.data.match` |
| Their accounts (`accounts`) | `ops.action.tool` |
| The account to hold (`facts`) | `ops.data.set` |
| Work out the hold (`calc`) | `ops.data.compute` |
| Anything to hold? (`enough`) | `ops.flow.if` |
| Approve the hold (`review`) | `ops.flow.humanReview` |
| A supervisor decides (`supervisor`) | `ops.flow.humanReview` |
| Place the hold (`hold`) | `ops.action.tool` |
| Place the hold (`hold_by_supervisor`) | `ops.action.tool` |
| Open a case (`case`) | `ops.action.openCase` |
| Note the hold on the case (`note`) | `ops.action.addToCase` |
| Tell the outside system (`notify`) | `ops.action.tool` |
| Held (`held`) | `ops.flow.end` |
| No such customer (`not_found`) | `ops.flow.end` |
| Nothing to hold (`no_funds`) | `ops.flow.end` |
| Declined (`declined`) | `ops.flow.end` |
| Could not finish (`failed`) | `ops.flow.end` |

| From | Port | To |
|---|---|---|
| `start` | payload | `search` |
| `search` | ok | `match` |
| `search` | refused | `failed` |
| `search` | error | `failed` |
| `match` | matched | `accounts` |
| `match` | none | `not_found` |
| `accounts` | ok | `facts` |
| `accounts` | refused | `failed` |
| `accounts` | error | `failed` |
| `facts` | out | `calc` |
| `calc` | out | `enough` |
| `calc` | error | `failed` |
| `enough` | true | `review` |
| `enough` | false | `no_funds` |
| `review` | approve | `hold` |
| `review` | reject | `declined` |
| `review` | timeout | `supervisor` |
| `supervisor` | approve | `hold_by_supervisor` |
| `supervisor` | reject | `declined` |
| `hold` | ok | `case` |
| `hold` | refused | `failed` |
| `hold` | error | `failed` |
| `hold_by_supervisor` | ok | `case` |
| `hold_by_supervisor` | refused | `failed` |
| `hold_by_supervisor` | error | `failed` |
| `case` | opened | `note` |
| `case` | error | `failed` |
| `note` | added | `notify` |
| `note` | error | `failed` |
| `notify` | ok | `held` |
| `notify` | refused | `failed` |
| `notify` | error | `failed` |

## attachment_record

Record what an attachment is. Recognises a file as one of the team's document types, reads it, and keeps the read on the file.

| Step | Type |
|---|---|
| File to record (`start`) | `ops.trigger.request` |
| Recognise and read it (`read`) | `ops.ai.extract` |
| Keep the read on the file (`save`) | `ops.files.setData` |
| Recorded (`recorded`) | `ops.flow.end` |
| Not readable (`unreadable`) | `ops.flow.end` |
| Could not finish (`failed`) | `ops.flow.end` |

| From | Port | To |
|---|---|---|
| `start` | payload | `read` |
| `read` | ok | `save` |
| `read` | review | `save` |
| `read` | unreadable | `unreadable` |
| `read` | error | `failed` |
| `save` | ok | `recorded` |
| `save` | error | `failed` |

## complaint_triage

Complaint email triage. A customer's complaint by email: each attachment is recognised and its read kept on the file, the complaint is read and triaged by an agent, it joins the customer's case or opens one, a hold starts when they ask for one, and they get a reply once a person approves it.

| Step | Type |
|---|---|
| Complaint received (`mail`) | `ops.trigger.email` |
| What came in (`what`) | `ops.flow.switch` |
| Record each attachment (`each`) | `ops.action.workflow` |
| Read the complaint (`read_body`) | `ops.ai.extract` |
| Put the facts together (`combine`) | `ops.data.combine` |
| Triage the complaint (`triage`) | `ops.ai.agent` |
| By urgency (`urgency`) | `ops.flow.switch` |
| Urgent (`urgent`) | `ops.data.set` |
| Normal (`normal`) | `ops.data.set` |
| Low (`low`) | `ops.data.set` |
| Did they quote a case? (`has_case`) | `ops.flow.if` |
| Add to their case (`add`) | `ops.action.addToCase` |
| Open a case (`open`) | `ops.action.openCase` |
| Do they ask for a hold? (`wants_hold`) | `ops.flow.if` |
| Start a hold (`hold_once`) | `ops.action.workflow` |
| No mailbox or sender? (`reply_check`) | `ops.flow.if` |
| Approve the reply (`ack`) | `ops.flow.humanReview` |
| Reply to the customer (`reply`) | `ops.action.tool` |
| Replied (`replied`) | `ops.flow.end` |
| Not replied (`no_reply`) | `ops.flow.end` |
| Nothing to read (`unreadable`) | `ops.flow.end` |
| Could not finish (`failed`) | `ops.flow.end` |
| Nothing to reply to (`nothing_to_reply`) | `ops.flow.end` |

| From | Port | To |
|---|---|---|
| `mail` | payload | `what` |
| `what` | attachments | `each` |
| `what` | body_only | `read_body` |
| `what` | otherwise | `unreadable` |
| `each` | started | `read_body` |
| `each` | error | `read_body` |
| `read_body` | ok | `combine` |
| `read_body` | review | `combine` |
| `read_body` | unreadable | `failed` |
| `read_body` | error | `failed` |
| `combine` | out | `triage` |
| `triage` | ok | `urgency` |
| `triage` | error | `failed` |
| `urgency` | high | `urgent` |
| `urgency` | normal | `normal` |
| `urgency` | otherwise | `low` |
| `urgent` | out | `has_case` |
| `normal` | out | `has_case` |
| `low` | out | `has_case` |
| `has_case` | true | `add` |
| `has_case` | false | `open` |
| `add` | added | `wants_hold` |
| `add` | error | `open` |
| `open` | opened | `wants_hold` |
| `open` | error | `failed` |
| `wants_hold` | true | `hold_once` |
| `wants_hold` | false | `reply_check` |
| `hold_once` | started | `reply_check` |
| `hold_once` | error | `reply_check` |
| `reply_check` | true | `nothing_to_reply` |
| `reply_check` | false | `ack` |
| `ack` | approve | `reply` |
| `ack` | reject | `no_reply` |
| `reply` | ok | `replied` |
| `reply` | refused | `failed` |
| `reply` | error | `failed` |

## two_source_match

Match a notice to the bank. Compare what a notice says with what the bank holds for the same account: both sources meet at a Join, Combine facts lists any field they disagree on, and a person settles a disagreement. The /wf-builder skill adapts this example.

| Step | Type |
|---|---|
| Request (`start`) | `ops.trigger.request` |
| What the notice says (`notice`) | `ops.data.set` |
| What the bank holds (`bank`) | `ops.data.set` |
| Both sources read (`join`) | `ops.flow.join` |
| Compare the sources (`combine`) | `ops.data.combine` |
| Matched (`matched`) | `ops.flow.end` |
| Settle the disagreement (`review`) | `ops.flow.humanReview` |
| Settled (`settled`) | `ops.flow.end` |
| Sent back (`sent_back`) | `ops.flow.end` |

| From | Port | To |
|---|---|---|
| `start` | payload | `notice` |
| `start` | payload | `bank` |
| `notice` | out | `join` |
| `bank` | out | `join` |
| `join` | out | `combine` |
| `combine` | out | `matched` |
| `combine` | disagree | `review` |
| `review` | approve | `settled` |
| `review` | reject | `sent_back` |
