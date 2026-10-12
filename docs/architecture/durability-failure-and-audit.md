# Durability, failure and audit

Status: current, updated 2026-10-11 against HEAD; every decision is an option until the owner confirms it.

LangGraph saves state between nodes. Keeping a run alive for days, with one owner at a time and no duplicated side
effect, is our code, all in the same PostgreSQL. Fencing and timers are decided in
[ADR-0016](decisions/fencing-and-timers.md); failure handling by side-effect class in
[interpreter-and-nodes](../specs/interpreter-and-nodes.md) §7.

## Durability mode

Runs use `durability="sync"`: the checkpoint is written before the next node starts. LangGraph's default, `async`,
writes a step's checkpoint while the next step already runs, so a refused write does not stop the next step's model and
tool calls, and a crash can lose the last step's checkpoint. Cost: one checkpoint write on each step's critical path,
3 to 9 ms unloaded.

## Leases and the sweeper

| Fact | Detail |
|---|---|
| Lease row | `thread_leases(thread_id, owner, run_id, acquired_at, heartbeat_at, expires_at, generation, released_at)` |
| Acquire | One `INSERT … ON CONFLICT DO UPDATE … WHERE expires_at < now() RETURNING`: taking over an expired lease and refusing a live one are the same statement. Lease times use PostgreSQL's `now()` |
| Refusal | 409 `run_active` with `{owner, runId, ageSeconds}`; two processes starting one thread at the same instant: exactly one runs |
| Heartbeat | Every TTL/3 while the run lasts. A lost heartbeat stops the run at its next stream event (`lease_lost`) |
| Sweeper | Every sweep interval, in every API process: takes over an expired lease with the same statement, marks the dead run `crashed` with its owner, running nodes and generation, and runs the graph with no input, so LangGraph continues from the last checkpoint. A run that died before its first checkpoint restarts from the input kept in `graph_runs.input` |
| Defaults | Lease TTL 15 s, sweep 3 s, timer poll 1 s (`OPS_LEASE_TTL_SECONDS`, `OPS_SWEEP_INTERVAL_SECONDS`, `OPS_TIMER_POLL_SECONDS`) |
| Recovery time | With TTL 6 s and a 1 s sweep: kill to recovery start 5.4 to 5.5 s (bound: TTL minus time since the last heartbeat, plus up to one sweep); kill to the next pause 12.2 to 12.9 s, about 7 s of which is the recovery's own model calls |
| TTL trade-off | Shorter recovers faster, costs more heartbeat writes, and lets a slow database or a GC pause expire a live lease, which fencing then has to catch |
| Recovery runs one at a time | Inside the sweep loop; a long recovery delays the others. Production should hand each recovery to its own task with a cap |

## Re-execution

A node killed mid-way runs again from its start on the new owner. Fan-out tasks that finished before the crash keep
their saved writes. A side effect inside a re-run node happens twice unless the receiver deduplicates it, so
deduplication lives where the call lands (tools-service), never in the process that might die.

| Call in a re-run node | What happens |
|---|---|
| Agent-kernel model call already completed, inside a graph run on PostgreSQL | Replayed from `model_calls` (`api/model_ledger.py`), keyed by thread and a hash of the request without timestamps and run ids; a re-run resume node makes no second call |
| Workflow model calls (classify, extract, draft, grade) | Repeat: 3 extra calls per crash in the dispute workflow's fan-out. The repeat may differ, though nothing downstream saw the first answer |
| Model call in flight at the crash | Repeats; a response is recorded only after its stream is read to the end |
| Tool write through tools-service | Runs once (dedupe below) |
| Usage rows | Written as each call returns, outside the checkpoint and unfenced, so a crashed attempt's spend is still counted |

## Fencing by generation

Fences are per thread: a process that pauses and takes its own thread back gets a new generation, and
its paused run's writes are refused. Every write a stale owner can make is checked inside its own transaction.

| Write path | Fenced | What a stale owner can still do |
|---|---|---|
| Checkpoint `aput`, `aput_writes` | Yes: `ops_checkpoint_fences`, raised by the new owner before its first read; a write with no generation on a fenced thread is refused | Nothing |
| Tool writes in tools-service | Yes: `gateway_fences`, checked in the dedupe claim's transaction before the replay lookup; raised by `POST /v1/fences` at takeover | A write that reaches tools-service before the fence call is ordered before the takeover and passes |
| Run journal (start, finish, crash mark) | Yes, against the lease row `FOR SHARE` | A late finish is appended as `stale_owner_finished` |
| Thread status, timers, SLA journal, timer claims | Yes | Nothing |
| Lease heartbeat and release | By `run_id` match | Nothing; a failed heartbeat is how it notices |
| Tool reads | No | Reads |
| Its own client's SSE stream | No | Shows stale progress until the run stops |
| Model calls in the step it was in | No | Pays for them; `sync` durability stops it at the step boundary |
| Side effects that bypass tools-service (in-process tools, `LocalReplySender`) | No | Anything; only tools behind tools-service are fenced |

| Fact | Detail |
|---|---|
| Cost | About 0.55 ms per checkpoint write at p95 (one upsert on a one-row-per-thread table) |
| Takeover detection | An acquire that replaces a lease never released is a takeover; it calls tools-service's fence before resuming. A finished run's next acquire is not a takeover and adds no call |
| tools-service down at takeover | The takeover proceeds and journals `lease.fence_not_raised`; the gap lasts until the new owner's first tool write |
| Lock order | A transaction past the fence holds a share lock on the lease row; releasing the lease from another connection while it is open deadlocks. Release only after the transaction closes |
| In practice | The heartbeat notices first; fences are the backstop for writes already in flight |

## Idempotency

| Layer | Key | Effect |
|---|---|---|
| Run | `runId` | A repeated run id replays the stored events |
| Thread | `externalKey` | A repeated key returns the existing thread |
| Tool write | `(thread, step, tool, inputHash)`, unique partial index on effecting rows | A retry returns the first result and logs a `replayed` row |
| Timer | `timer_id` (interrupt id and round) | A duplicate or early fire does nothing |
| Kernel tool call | `run_id:turn_id:step:ordinal` | Passed to the tool as its idempotency key |

A gateway that dies after claiming a write and before the tool returns leaves a `running` row; every retry then gets
409 `write_in_progress` and nobody knows whether the effect happened. That needs a reconciler that asks the tool
server; it is not built.

## Side-effect classes

| Class | Example | Retries | When it still fails |
|---|---|---|---|
| none | classify, grade | Three, with backoff | Manual handling |
| read | Look up a wire | Three, with backoff | Manual handling |
| write, idempotent | Add a case note with a key | Three, same key | Manual handling |
| write, not idempotent | Send a reply | One attempt, then a reconciliation read | Manual handling if the read cannot tell |
| money | Place a wire hold | One attempt, then a reconciliation read; approval token from two approvers | Manual handling |

No run ends silently: a failed or stuck run, a recursion limit hit, or a timer past its retry cap lands in manual
handling, shown in Reviews. Retries by class and the manual-handling queue are designed; today a node error ends the
run with `error` and the checkpoint keeps the last good step.

Route to people is built for definition workflows: `POST /v1/threads/{id}/route-to-people`, or
`POST /v1/threads:route-to-people` for every open thread of one workflow version. The request sets a flag on the
thread; `execute` reads it before starting and after every step that ends with no write step in flight, so a write in
flight finishes and in-flight reads are cancelled. The skipped steps are journaled as `route.skipped`, and the thread
continues to the built-in `manual_handling` step, which waits for a person with the reason. A waiting or idle thread is
routed at once under its lease. Code graphs answer 409 `not_routable`. The publisher role is not checked: dev auth
has no roles, so the requester is recorded.

## Approval expiry

A decision resumes at once, but a resume retried after a busy lease, or a run the sweeper recovers, can reach the
gateway after the token's TTL. The agents service renews the token from the recorded approvals of that exact call
(thread, step, tool, input hash, the same approvers) while they are younger than `approval_renewal_max_age_seconds`
(24 h); past that, the call fails asking for a fresh review (`api/approval_renewal.py`, uc-027).

| Option | For | Against |
|---|---|---|
| Renew from recorded approvals (chosen) | No second review for an approval already given; covers retries and crash recovery; nothing changes at the gateway | The approval, not the token, now bounds the window: an approval can act up to 24 h after it was given |
| Raise a fresh review on `token_expired` | The reviewer sees the call again | Asks again for every late resume, including after a crash the reviewer had nothing to do with; a run stalls until someone decides twice |

## The journal

| Aspect | Designed | Today |
|---|---|---|
| Shape | Append-only table; rows never changed or deleted inside retention | `graph_runs`: one row per run with its events, written at run end, plus `sla` and `lease` rows; run events also go to `thread_events` as they happen, so a crashed run's events up to the crash survive |
| Fields per step | `sub`, `act`, token id, input hash, gateway decision, model call id, tool call id, node, version digest, time | Node sequence, owner, generation, crash record; tool decisions in `gateway_calls` |
| Retention | Set per tenant; checkpoints are pruned, the journal is kept | No retention job |
| Export | Signed JSON lines to the tenant's storage on a schedule | No |

## Checkpoint growth and pruning

From [checkpoint-growth](../services/agents-service/experiments/checkpoint-growth.md), dispute workflow, 20
attachments of 2 KB:

| Measure | Value |
|---|---|
| Rows per thread | 9 checkpoints, 81 writes |
| Payloads in state | 869 KB raw per thread (411 KB after TOAST); largest checkpoint 124 KB; p95 write 9 ms |
| References in state | 72 KB raw per thread; largest checkpoint 11 KB; p95 write 5.3 ms |
| Write latency | About 20 ms per MB at p95 unloaded; passes 50 ms near a 2 MB checkpoint (about 30 KB per attachment × 20) |
| Under load | 20 cases at once: same checkpoints at 67 ms p95; PostgreSQL 116% of one core, 3,056 commits/s, 17 MB/s WAL |

| Rule | Why |
|---|---|
| State holds references, never payloads | Our saver stores the whole state per superstep; references cut storage 12× and keep checkpoints flat as attachments grow |
| Never copy a payload between state keys | The dispute workflow copied each attachment twice, doubling checkpoints |
| Send packets are stored in the checkpoint | A fan-out step's checkpoint carries every pending packet's payload |
| Prune only an idle thread with a finished run and no running run | `prune_thread` checks the journal first; a paused thread is never pruned |
| Delete a closed thread's checkpoints once the journal holds the record | `keep_latest` keeps the heaviest checkpoint (the full final state, about 52 KB per thread here) |
| Schedule maintenance | Pruning deletes rows and returns no disk space. VACUUM makes space reusable, only VACUUM FULL (exclusive lock) or partitioning returns it; write-table indexes bloat until REINDEX |
| Report raw and stored bytes | TOAST compression hides size; repeated test text compressed 25× and made checkpoints look like 3 KB |

msgpack against JSON made no difference (90.6 against 91.9 KB). A saver that stores channel values per version, as
LangGraph's own PostgreSQL saver does, would store attachments once per thread instead of once per step; estimated
9× less for payload-heavy state, not measured.
