# A hold on a customer's account

Status: passing (2026-10-19). Id: `uc-248`. Service: `agents-service`. Layers: ui. One of the two workflows that
between them run every node type (`docs/services/agents-service/workflow-node-coverage.md`).

`customer_hold` is a request workflow. It finds the customer in the bank, checks it is them (the name plus either the
last four of their SSN or their email address), works out how much of the requested amount the account can hold, and
asks a person to approve within four hours. Past the deadline the review expires to a supervisor. The approved hold is
placed through the tools gateway, a case opens with the hold's figures, the hold is noted on the case, and the outside
system is told by webhook. Nothing is faked but the bank. No model call.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA for the isolated stack | `make db-up ISOLATED=1` |
| The run | `make usecase-test UC=uc-248 LAYER=ui ISOLATED=1` |

The stack is the banker demo (`withUiStack({ demo: true })`) with the core fake bank and its webhook stand-in. Placing
a hold needs two approvers, each re-authenticating first (the operation's approval policy).

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James starts a hold of 2000 on Marcus Bell (last four 4471) | Request, Look up the customer (`search:ok`), Is it them? (`match:matched`), Their accounts (`accounts:ok`), The account to hold (`facts:out`), Work out the hold (`calc:out`, hold 2000), Anything to hold? (`enough:true`); it waits at Approve the hold |
| 2 | Maya approves on Human Tasks with a step-up, then Priya | Place the hold (`hold:ok`), Open a case (`case:opened`, field `held` 2000), Note the hold on the case (`note:added`, a `holdId`), Tell the outside system (`notify:ok`, one `hold.placed` payload for the case); outcome `held` |
| 3 | A hold on a name the bank does not know | `match:none`, outcome `customer_not_found` |
| 4 | A hold of 0 on Jordan Whitfield | `enough:false`, outcome `nothing_to_hold` |
| 5 | A copy with a deadline under two seconds, on Priya Natarajan | `review:timeout`; a supervisor's review; Priya and Maya approve; `hold_by_supervisor:ok`, `case:opened`, `note:added`, outcome `held` |
| 6 | James opens `customer_hold` in the editor and the Open a case step | Priority shows `high`: the choice list reads the choices from a setting that also takes a path |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `agents-service/scripts/test-uc-248-ui.mjs` | passing |

## Non-vacuous check

Step 2 failed while the approvals were sent without a step-up (422 `step_up_required`) and while only one person
approved. Step 5 failed while the copy's publish was not approved: the start was refused and no review timed out.
