# Human in the loop

Status: current, updated 2026-10-11 against HEAD; every decision is an option until the owner confirms it.

A pause is an interrupt in a graph: state is saved, nothing runs, and the thread waits for one decision. A two-person
approval, an SLA timeout and a customer reply all use the same shape; only what the interrupt needs and what decides
it change. Node-level detail is in [interpreter-and-nodes](../specs/interpreter-and-nodes.md) §4; tokens in
[ADR-0005](decisions/identity-and-entitlement.md); step-up in [sign-in-and-sessions](../specs/sign-in-and-sessions.md) §3.7. Token facts and the trust shortcuts still in the
code are in [identity-and-tenancy.md](identity-and-tenancy.md).

## Interrupt kinds

| Kind | Raised by | Payload | Who resumes it |
|---|---|---|---|
| Approval of a tool call | `agent_wrapper` approval node; a workflow `human` node before `send_reply` | `call = {tool, input, step}`, `moves_money`, reviewers group, `sla` block | A review decision with an approval token |
| Review of a draft | Workflow `human` node | Draft, evidence, citations, the call it gates | A review decision |
| Question to the chat user | An agent node, owned by no policy | The question | The user, through `runs` |
| Timeout | The timer poller through `fire()` | `{"decision": "timeout", "timer": "breach" or "maxWait"}` | The runtime alone, from the pinned plan |
| Budget exhausted | A metered model call on a thread whose budget is spent, before the call (`graphs/metering.py`) | `{kind: "budget_exhausted", node, limit, spent, cap}` | A person through `runs`: approved with a higher `budget` continues; rejected ends the run in error |
| Manual handling | `POST /v1/threads/{id}/route-to-people` (definition workflows only); designed also for a run past its retry budget or recursion limit | The reason; remaining steps journaled as `route.skipped` | A person, at the built-in `manual_handling` step |

## Rules for the human step

| Rule | State |
|---|---|
| The approval interrupt is its own node, before any side effect, so resume never re-runs a write | In code |
| Decide is the only door for a policy-owned interrupt; `runs` answers 409 for it | Partial. `POST /reviews/{threadId}/decision` records the decision keyed by the interrupt id, then resumes; a repeat with the same decision resumes at most once (uc-008). `POST /v1/threads/{id}/runs/stream` still accepts a resume |
| One signed approval token per action, bound to one call's input hash | In code ([token facts](identity-and-tenancy.md#approval-and-step-up-token-facts)) |
| Any edit to the input after approval invalidates every approval of it | In code: only approvals with the current hash count |
| The requester cannot decide | In code for workflow reviews: `POST /reviews/{id}/decision` refuses the person recorded on the interrupt, or the workflow's process principal, with 403. Chat honours `allow_self_approval_in_chat` (default true until the owner decides; uc-009 runs it false). `POST /v1/threads/{id}/approvals` has no requester check |
| Step-up authenticates the approver and approves nothing by itself | In code: verified for signature, subject and five-minute age on every money decision ([token facts](identity-and-tenancy.md#approval-and-step-up-token-facts)) |
| Money needs two distinct approvers; the API collects both, then resumes once | In code: the approvals route returns a token only at two approvers and refuses the same approver twice (403); OPA refuses one |
| Parallel interrupts resume as one map `{interrupt id: decision}` collected by the API | Designed |
| A timeout never approves | In code |
| Review policies live in the workflow draft and are pinned at publish; the policy call is read only | Designed; SLA settings already live in the `human` node's config |

## Decide then resume

The decision is recorded first in `review_decisions`, keyed by thread and the paused interrupt's id (the decision
id), then the thread is resumed under a run id derived from it. If the resume fails (another run holds the lease, a
crash) the decision stands with `resumed_at` unset, and the next decide with the same decision resumes once. A
different decision on an already decided review answers 409 `already_decided`. When a gated call needs a token, the
decide path records the approver through the approvals route and resumes only once enough approvers exist; until then
the review reports `in_review` with the approvers so far.

## SLA timers

Each `human` node takes `{group, sla, warnAt, onTimeout: reassign | escalate | reject, escalateTo, reassignTo,
maxWaitDays}`; durations look like `2s`, `30m`, `4h`, `3d`, and invalid ones fail validation. The timeout outcome is
part of the published definition, so the runtime decides alone when a timer fires, with no call to another service.
hitl-service (planned) learns of it to resolve groups to people, notify and record the outcome.

| Event | What happens |
|---|---|
| Warn | Journaled as `sla.warn`; no resume, no lease. At most once: a crash between the claim and the journal loses the event |
| Breach | `onTimeout` runs: reassign or escalate raises the interrupt again to the new group with a fresh clock (round + 1); reject ends with `rejected`. An escalated review gets no breach timer of its own |
| Max wait | Always rejects, whatever round the review is in |
| Customer reply | `POST /v1/threads/{id}/events {"type": "customer_reply"}` cancels warn and breach and re-arms them from now; max wait keeps running |
| Decision before the SLA | Its timers are cancelled at the end of that run |

| Mechanism | Fact |
|---|---|
| Table | `timers(thread_id, timer_id, kind, node, interrupt_id, due_at, fired_at, cancelled_at, claimed_generation, claimed_at, attempts, failed_at)` |
| Keying | By interrupt id and round, because LangGraph gives every interrupt raised in one task the same id (observed in 1.2.14, undocumented). The round separator is `.r`: a `#` in the fire URL truncated the path to a 404 |
| Arming | `sync_timers` runs at the end of every `execute`, before the lease is released, so a poller never sees a waiting thread without its timers |
| Firing | `fire(thread, timer)` is the only path, behind `POST /v1/threads/{id}/timers/{timerId}/fire`. Idempotent; returns `fired`, `duplicate`, `not_due`, `not_waiting`, `busy` or `retry`, or 409 when the timer will never fire |
| Under the lease | `fire` takes the thread's lease and re-checks in one transaction that the timer is due, open, and its interrupt and round still wait. A held lease means try again next poll |
| Claim | A fenced claim replaces a row lock held for the step's duration, so `idle_in_transaction_session_timeout` no longer matters |
| Retry cap | Three claims without the step finishing set `failed_at` and journal `sla.fire_failed` for a person |
| Clock | Due and fired times use PostgreSQL `now()`; a scheduler with a fast clock gets `not_due` |
| Scheduler | The PostgreSQL poller (`FOR UPDATE SKIP LOCKED` on a partial index) is the only one shipped. `TimerScheduler` is a port for a later scheduler; a cloud scheduler needs OIDC or mTLS on the fire route |
| Latency | At 1 s polling: median 0.46 s, worst one interval. At 5 s: median 3.08 s |
| Idle cost | One read-only transaction per poll, no rows written, no WAL |
| PostgreSQL only | On SQLite the poller does not start; every timer test runs on PostgreSQL |
| No live subscriber | A poller-driven run has no client stream; its record is the run journal and the state |

## What a pause looks like per channel

| Channel | The pause shows as | The decision arrives from |
|---|---|---|
| Console chat | An approval widget in the reply; money opens "Confirm it is you" | The widget, or the Reviews page |
| Mailbox | A review task with an SLA; nothing is sent until approval | Reviews page, or a mail or Teams button (planned) |
| API | `status: waiting_review`, polled or sent by webhook | The caller's review client |
| MCP | A result with status pending and a review id only; the case stays in the console | Reviews page |
| Schedule, webhook | A review task | Reviews page |

Every one of these sends the same decide call. Which risk tiers let a chat user approve their own drafted write is an
open decision ([delivery.md](delivery.md)).
