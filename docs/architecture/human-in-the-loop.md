# Human in the loop

Status: current, updated 2026-10-18. The decided design is [workflows and agents](../design/workflows/workflows-and-agents.md); decision records it does not settle remain options.

A pause is an interrupt in a graph: state is saved, nothing runs, and the thread waits for one decision. A two-person
approval, an SLA timeout and a customer reply all use the same shape; only what the interrupt needs and what decides
it change. Node-level detail is in [workflow nodes](../design/workflows/workflow-nodes.md) §4; tokens in
[ADR-0005](decisions/identity-and-entitlement.md); step-up in [sign-in library](../packages/ops_signin/overview.md) §3.7. Token facts and the trust shortcuts still in the
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
| The requester cannot decide | Being changed: no hard-coded rule; the team's `requesterMayDecide` policy decides, and a step's `notDecidedBy` carries the people it excludes. Today, in code for workflow reviews: `POST /reviews/{id}/decision` refuses the person recorded on the interrupt, or the workflow's process principal, with 403. Chat honours `allow_self_approval_in_chat` (default true until the maintainers decides; uc-009 runs it false). `POST /v1/threads/{id}/approvals` has no requester check |
| Step-up authenticates the approver and approves nothing by itself | In code: verified for signature, subject and five-minute age on every money decision ([token facts](identity-and-tenancy.md#approval-and-step-up-token-facts)) |
| Money needs two distinct approvers; the API collects both, then resumes once | In code: the approvals route returns a token only at two approvers and refuses the same approver twice (403); OPA refuses one |
| Parallel interrupts resume as one map `{interrupt id: decision}` collected by the API | Designed |
| A timeout never approves | In code |
| Review policies live in the workflow draft and are pinned at publish; the policy call is read only | Designed; SLA settings already live in the `human` node's config |

## Task types and the task screen

Designed and approved on 2026-10-18. The design, with wireframes and five use
cases, is [the task page design](../design/human-tasks/task-page.md). Ops AI serves thousands of use cases, so no task
screen is written for one of them.

| Part | Decision |
|---|---|
| Task type | A versioned database record: a parameters schema with a fallback per parameter, an ordered list of regions from a fixed set (header, why and source, document with field boxes, facts, write preview, form, message, history), and actions (label, consequence, whether a reason is needed, tone, the output port, and optional inputs such as an assignee) |
| Seeded types | generic_decision, document_check, write_approval, acknowledgement, data_entry. A specialised type is a copy a builder edits; no type is code |
| Who picks it | The humanReview step, or a caller of the review API, names a type by id and version and passes its parameters. A task pins the version it was created with |
| Bad input | A value of the wrong kind is refused with 422 naming the field. A missing optional value falls back. A missing required step setting warns on save and never blocks it |
| Many doubtful fields | The workflow or document type marks the key fields. They come first and must be checked; the rest can be accepted together |
| Reject | Goes to the team's queue; the person deciding may name someone |
| Who decides | Approve and Reject alike: a reviewer of the approving team of each write the task holds, else of the run's or thread's team. The task names that team (`decidingTeam`, with its name read live from platform-service) and says what approving does |
| Old reviews | A review paused before its step named a task type still draws as one (`api/legacy_tasks.py`). If the workflow's live version now names a type on that step, the review uses it, with the step's params resolved against the run's steps; a list reads every listed run's steps in one query (`TaskReads.steps`). Otherwise what the review carries (a read, a reply, a write, a decision) picks a seeded type from `seed/legacy_task_types.json`. A step with options other than approve and reject keeps its options |
| Screen | A full page: a header with the one question, a scrolling body with the evidence first and everything else collapsed under Details, and a fixed footer with the actions that never covers content. The list keeps a wider quick view. Regions render through the console's widget renderer, the same one chat uses. No engine words (gates, run ids, event names) appear on the page |

## Task API, task assist and queue place

| Part | What the code does |
|---|---|
| Task API | `POST /v1/tasks` takes `{type, version?, params}` (`services/agents-service/src/ops_agents/api/routers/tasks.py:101`). It needs `workflows.run` in the acting team (`X-Team-Id`, else the caller's team). A value of the wrong kind is 422 `invalid_task_params` naming the field; a missing required value is accepted with a warning. It records a `task.requested` event ([service-map](service-map.md#service-events)), which starts the `api_task` workflow. The reply holds the task id (the run id), the console `url`, `status` (`waiting` once the run reaches the step, `starting` if it has not within 5 s), the pinned version and the warnings. 422 `task_unhandled` when no workflow handles the event |
| Reading the decision | `GET /v1/tasks/{id}` returns `status`, and once decided the `action` (the out port), `reason`, `decidedBy`, `decidedAt` and `values` (a reviewer's corrections or an action's inputs). There is no webhook; the caller polls |
| Task types | `GET /v1/task-types`, `GET /v1/task-types/{id}`, `POST /v1/task-types`, `PUT /v1/task-types/{id}/draft`, `POST /v1/task-types/{id}/publish` (`api/routers/task_types.py`). Every member of the tenant reads every type; create, save and publish need `workflows.create`, `workflows.edit`, `workflows.publish` in the owning team. A seeded type is read-only and is copied to change it |
| Task assist | Off until the team turns on the `taskAssist` policy. When a typed review step pauses, `TaskAssist.write` (`api/task_assist.py`) makes one prompt-only model call over the task's bound regions and writes `{question, summary, doubtful, suggestion{action, reason}}` to `task_assists`, keyed by step id and written once. The task view inserts it as an `assist` region marked `ai`, after the header (`api/task_view.py:52`). A suggestion naming an action the type lacks is dropped on read. It decides nothing |
| Task assist limits | The pause waits at most 20 s for the call; on a failure or timeout the task opens without an assist. |
| Queue place | `GET /reviews/{id}/place?view=open` (`api/routers/reviews.py:188`) returns `position`, `total`, `previous` and `next` for a review in a Human Tasks view, from `hitl_facade.queue_place` (`api/hitl_facade.py:654`). A run id resolves to the review it waits on. `position` is null when the review is not in the view. It builds the list of every review in the view on each call (`all_reviews`) It reads the views' rows by id and status alone, in the list's order, and builds no review, except for `view=overdue`, which needs each review's deadline |

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
The Reviews code, in agents-service today and in the `ops_hitl` package once it moves, learns of it to resolve groups
to people, notify and record the outcome.

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
| Firing | `fire(thread, timer)` is the only path, called in-process by the timer poller; no HTTP route fires a timer (c-168). Idempotent; returns `fired`, `duplicate`, `not_due`, `not_waiting`, `busy` or `retry`, or 409 when the timer will never fire |
| Under the lease | `fire` takes the thread's lease and re-checks in one transaction that the timer is due, open, and its interrupt and round still wait. A held lease means try again next poll |
| Claim | A fenced claim replaces a row lock held for the step's duration, so `idle_in_transaction_session_timeout` no longer matters |
| Retry cap | Three claims without the step finishing set `failed_at` and journal `sla.fire_failed` for a person |
| Clock | Due and fired times use PostgreSQL `now()`; a scheduler with a fast clock gets `not_due` |
| Scheduler | The PostgreSQL poller (`FOR UPDATE SKIP LOCKED` on a partial index) is the only one shipped. `TimerScheduler` is a port for a later scheduler; a cloud scheduler needs OIDC or mTLS on the fire route |
| Latency | At 1 s polling: median 0.46 s, worst one interval. At 5 s: median 3.08 s |
| Idle cost | One read-only transaction per poll, no rows written, no WAL |
| PostgreSQL only | On SQLite the poller does not start; every timer test runs on PostgreSQL |
| No live subscriber | A poller-driven run has no client stream; its record is the run journal and the state |

### Deadlines and reminders on a workflow's Human review

The timers above are the v1 graph runtime's. A workflow's Human review on the v2 engine keeps no timers table: its
deadline and its reminders are rows in the engine's work queue (`engine_work`), queued when the run pauses and keyed so
a pause found again queues none twice (`packages/ops_engine/src/ops_engine/worker.py`).

| Setting | What happens |
|---|---|
| `slaHours` with `onTimeout: expire` | A `timeout` row keyed by run, step and iteration, due after the deadline (the workspace's `reviewSlaHours` when unset). Due while the review still waits, it resumes the run by the `timeout` port; a review decided first drops it |
| `remindEveryHours` | A `remind` row per reminder, keyed by run, step, iteration and count, timed from the review's `openedAt`. Due while the run still waits at the same pause (same interrupt id), it records a `reminded` run event and a `task.reminder` service event (Activity kind `reminder`), queues the next, and never resumes the run; a decided review takes none (c-277) |

What a reminder does next, an email or a reassignment, is a workflow a team adds for `task.reminder`; none is shipped.
Proof: `services/agents-service/tests/engine/test_review_deadline.py`, `test_wait_and_reminders.py`; uc-403.

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
