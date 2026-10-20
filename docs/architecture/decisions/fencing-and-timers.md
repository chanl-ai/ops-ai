# ADR-0016 Fencing and timers

Status: superseded in part on 2026-10-16: the maintainers removed Temporal, so the Temporal adapter and the Temporal oracle in the recommendation no longer apply; fencing by lease generation carries into `ops_engine` (see `.codeloop/wiki/concepts/system-overview.md`). Earlier status: option, not decided. No ADR has been confirmed by the maintainers as of 2026-10-10; each one records the options, a scoring and a recommendation, and the build keeps a seam open so the choice can differ per enterprise deployment.

## Context

[ADR-0015](execution-engine-seam.md) builds the LangGraph-on-PostgreSQL engine first: our own checkpointer (E0), per-thread leases with a heartbeat and a sweeper (E2), and a tool gateway that dedupes writes against an approval token (E3). Two problems remain, and the maintainers asked for them to be rethought against how others solve them.

**Fencing (E2b).** A worker that stalls (GC pause, network partition, SIGSTOP) loses its lease; the sweeper on another worker takes the thread over. The stalled worker then wakes and can still write a checkpoint, call the gateway, or write journal rows (E2 gotcha 3). Dedup in the gateway stops a second identical call; it does not stop a stale worker sending a different one (E3, row "Fencing"). the maintainers' question: do we fence a worker or a workflow?

**Timers (E5).** LangGraph has no durable timers. E5 built a `timers` table and an in-process poller, and it works (9 tests, median latency 0.46 s at a 1 s poll). the maintainers' idea: reduce a timer to an external call to our own fire endpoint, so the poller is one scheduler among several.

**Oracle.** Should we bring Temporal in now to expose gaps in our LangGraph durability, given that the Temporal adapter of ADR-0015 is not built?

## How others do it

### Stalled or duplicate worker after takeover

| System | What carries the fence | Who checks it |
|---|---|---|
| Temporal | Per-shard `RangeID` inside the server[^t-hist]; per-attempt task token for workers[^t-act] | History service; a late activity completion gets `NotFound`[^t-forum] (forum, **unverified** in docs) |
| Cadence | Same lineage as Temporal; workflow tasks are called decision tasks[^cad] | Same design (**unverified**: Cadence server internals not read) |
| DBOS | `executor_id` on each workflow row; recovery re-enqueues, one atomic claim admits one runner[^dbos-491] | Database claim. Duplicate in-process execution was a real bug, fixed in Java 2026[^dbos-491] |
| Restate | Leader epoch per partition; Bifrost log segment sealed on failover[^restate-arch] | Partition processor rejects events from superseded epochs[^restate-arch] |
| Inngest | None found; each step is a separate HTTP call whose result Inngest records[^inngest-exec] | Inngest's state store; docs ask for idempotent steps[^inngest-exec] |
| Azure Durable Functions | Blob lease per control-queue partition[^adf-storage] | Lease alone allowed ~10 s split brain; ETag on history writes proposed as fix[^adf-38] |
| AWS Step Functions | Task token per task; a new token on timeout[^sfn-cb] | `SendTaskSuccess` returns `TaskTimedOut` for an expired or closed token[^sfn-sts] |
| LangGraph Agent Server | Worker "acquires a lease" on the run; one run per thread[^lg-server] | No fencing of a stale worker documented; on crash another worker resumes[^lg-blog] |
| Kafka transactions | Epoch per `transactional.id`, bumped when a producer registers[^kafka] | Broker rejects writes from an older epoch[^kafka] |
| Lock services | Monotonic fencing token per lock grant; ZooKeeper `zxid`[^kleppmann]; Chubby sequencer (**unverified**) | The storage service, which remembers the highest token seen[^kleppmann] |

Every system that fences does it the same way: the token belongs to the unit of ownership (shard, partition, `transactional.id`, task attempt, lock), whichever process holds it, and the receiver of the write checks it. Temporal adds a second property: workers never write workflow state; they return commands, and the server applies them only if the task they answer is still the current one.

### Durable timers

| System | Where the timer lives | Notes |
|---|---|---|
| Temporal | Timer task in the history shard; fires `TimerFired` into history[^t-hist] | Seconds to years; no sub-second accuracy[^t-timer] |
| DBOS | Wake-up time stored in PostgreSQL; recovery sleeps the remainder[^dbos-wf] | Needs a live executor to own the sleeping workflow (our reading) |
| Restate | In the Restate server's partition state; sleep resumes the remainder[^restate-timer] | Awakeables: an id an external system resolves over HTTP[^restate-awk] |
| Inngest | In Inngest; no compute runs during `sleep`/`waitForEvent`[^inngest-exec] | Resume is a new HTTP call to the app |
| Azure Durable Functions | A queue message that becomes visible at the due time[^adf-timer] | Six-day cap in JS/Python/PowerShell; longer timers chained[^adf-timer] |
| AWS Step Functions | Wait state in the service; callback waits up to one year[^sfn-cb] | `HeartbeatSeconds` fails a silent callback with `States.Timeout`[^sfn-cb] |
| LangGraph Agent Server | Crons per thread or stateless, UTC cron syntax[^lg-cron] | No one-off delayed resume found in the cron docs |
| pg_cron | Job table in PostgreSQL; one instance per job at a time[^pgcron] | Recurring only, down to seconds; no one-off jobs[^pgcron] |
| `LISTEN`/`NOTIFY` | Nowhere durable: lost if no listener is connected[^pg-notify] | Usable as a wake-up hint beside a table, never alone |
| Google Cloud Tasks | Task with `scheduleTime`, HTTP target with OIDC auth[^gct] | Up to 30 days ahead; at-least-once; names dedupe[^gct-quota] |
| AWS EventBridge Scheduler | One-time `at()` schedule invoking a target[^eb] | 60 s precision; completed one-time schedules count against quota[^eb] |

### Idempotent side effects on replay

| System | Mechanism |
|---|---|
| Temporal | Workflow code replays from history; activities are at-least-once, so activity code must be idempotent[^t-act] |
| DBOS | Step outputs checkpointed; a completed step never re-runs; workflow id is an idempotency key[^dbos-arch][^dbos-wf] |
| Restate | Journal per invocation; a retry receives the journal and skips committed entries[^restate-arch] |
| Inngest | Step results memoised; event id and function idempotency key dedupe for 24 h[^inngest-idem] |
| Step Functions | Redrive reruns only the failed state, within 14 days[^sfn-redrive] |
| Durable Functions | Orchestrator replays from the history table; activities at-least-once[^adf-storage] |

None of them makes an external side effect exactly once. Each records completed steps and tells the user to send a stable key to the external service, because a call can succeed before its result is recorded[^inngest-idem].

## Options for us

### Fencing

**(i) Lease generation on every write path (E2b as proposed).** The conditional lease write increments `generation`; checkpoint, journal, events, timer claims and gateway calls carry it and are refused if it is stale.

| Pros | Cons |
|---|---|
| Same pattern as Restate, Kafka, Temporal's `RangeID` and Kleppmann | Every write path must check, and a missed path is a silent hole |
| All our stores but the gateway share one PostgreSQL, so the check can sit in the write's transaction | The gateway is a separate service and needs its own highest-seen generation per thread |
| Fences the thread, so one process holding many threads loses only the stolen one | Cannot reach past the gateway into a tool server |

What breaks: a write path added later without the check, such as a new events table, accepts stale rows.

**(ii) Fence only at the side-effect boundary; readers ignore stale checkpoints by generation.**

| Pros | Cons |
|---|---|
| Fewest changes: gateway plus idempotency keys | A stale checkpoint becomes the newest row; every reader (`get_state`, history, sweeper) must filter |
| Matches what Inngest and DBOS ask of users | Journal, events and timers still take stale rows |
| | Gateway dedupe does not stop a stale call with a different input (E3) |

What breaks: the stalled worker writes a checkpoint after B's; a reader that forgets the filter resumes from A's fork.

**(iii) Per-step task token issued at takeover (Temporal, Step Functions).**

| Pros | Cons |
|---|---|
| Finest grain: a late completion of one attempt is refused, as `TaskTimedOut` does | Needs a server that owns the attempt state machine; that is rebuilding Temporal's history service |
| Already true for approvals: E3's token covers exactly one call | LangGraph nodes write state directly, so no single server point applies commands and could check them |

What breaks: nothing new, but the cost is a second engine's worth of code inside engine B.

**(iv) Single writer by partition, takeover only after a quorum or consensus lease.**

| Pros | Cons |
|---|---|
| Fewer takeovers, because heartbeat loss is confirmed | Durable Functions used partition leases and still had split brain[^adf-38] |
| | Needs ZooKeeper, etcd or similar: the extra stateful server some banks refuse (ADR-0015) |
| | A paused process cannot know it lost the lease, so writes still need a fence |

What breaks: a GC pause longer than the lease; the paused owner writes after the new owner, as in (i) without checks.

### Timers

**(i) PostgreSQL table and poller inside the Runtime (E5 as built).**

| Pros | Cons |
|---|---|
| Built and tested; one dependency; due time on the database clock | Timer row stays locked while the step runs; `idle_in_transaction_session_timeout` breaks it (E5) |
| Idle cost measured: one read-only transaction per poll, no WAL | Accuracy is the poll interval |

What breaks: a deployment with a strict idle-transaction timeout loses no timer but retries it every poll.

**(ii) A timer port: the table stays the source of truth, `fire(timerId)` is the only way to fire, and schedulers only wake it.** `POST /v1/timers/fire {timerId}` is internal and idempotent: it re-checks, under the thread's lease and generation, that the timer is due, not cancelled, and that its interrupt and round still wait. Schedulers: the PostgreSQL poller (default), pg_cron, Cloud Tasks or EventBridge Scheduler calling the endpoint, or a Temporal timer.

| Pros | Cons |
|---|---|
| Same shape as Restate awakeables and Step Functions task tokens: the wait is ours, the signal is anyone's | External schedulers keep their own copy of "when"; cancel and reschedule leave stray calls, which the re-check absorbs |
| Tests call `fire` directly instead of waiting for a poll | Inbound HTTP from a cloud scheduler needs auth (OIDC) and an ingress banks may refuse |
| A late, early or duplicate wake-up is harmless by construction | Cloud Tasks caps at 30 days; EventBridge at 60 s precision[^gct-quota][^eb] |

What breaks: an external scheduler that is never told about a new timer; the poller still fires it, if it runs.

**(iii) Temporal timers only.** Correct and proven, but needs the Temporal adapter and the server, so engine B has no timers. What breaks: every bank that refuses Temporal.

**(iv) Redis sorted-set scheduler.**

| Pros | Cons |
|---|---|
| Sub-second wake-ups; reportedly what the Agent Server uses for leases (**unverified**, third-party blog[^lg-redis]) | A second stateful server; durability depends on AOF settings |
| | Two sources of truth for a timer, with no transaction across them |

What breaks: Redis restarts without AOF and loses every pending SLA breach.

### Temporal as an oracle

Days are estimates for one engineer.

| Option | Cost | What it would reveal | What it would not |
|---|---|---|---|
| (i) Build the adapter now, run the eight tests on both | 8–12 days | Real behaviour on stale workers, timers during a running task, update validation | Nothing about banks that refuse the server |
| (ii) Write the tests from Temporal's documented semantics, no Temporal | 2–3 days | Where our spec is silent: stale completion, timer firing mid-run, token expiry on recovery | Undocumented Temporal behaviour |
| (iii) Defer until a deployment asks | 0 days | Nothing | Risk that LangGraph habits leak into the interpreter |

## Recommendation

**Fencing: option (i), with the reading that we fence the workflow thread, carried by whichever worker holds it.** Every system read fences the unit of ownership and has the receiver check the token. A per-process fence fails in two ways: one process holds many threads and would lose all of them, and a process that pauses and re-acquires its own thread has the same identity but a stale view. Option (ii) leaves the checkpoint fork that E2 gotcha 3 describes. Options (iii) and (iv) cost a server we chose not to need. Idempotency keys stay as a second layer, because no fence reaches into a tool server; that part of (ii) is kept.

**Timers: option (ii), shipping only the PostgreSQL poller as a scheduler.** It reuses E5's table and tests and moves one function, because the poller already resumes through `runs.execute`. Making `fire` the only entry point with a full re-check is what makes any second scheduler safe later; building cloud adapters before a deployment asks is not justified.

**Temporal: option (ii) now, and the adapter when ADR-0015 schedules it.** The gaps this ADR found (stale completion, timer during a run, token expiry after recovery) are documented Temporal behaviour; encoding them as tests costs days, where running Temporal costs weeks. Add two tests to ADR-0015's suite: (9) a worker paused past its lease cannot write after takeover; (10) a timer due during a run fires once after the run ends, or is cancelled if the run decided.

### Changes to E2b

| Keep | Change |
|---|---|
| `generation` on `thread_leases`, bumped by the takeover write | The check must be in the write's own transaction (lease row `FOR SHARE`, or a conditional insert); a read-then-write is no fence |
| SIGSTOP/SIGCONT proof and the fence-cost measurement | Extend the check to journal rows, events and timer claims, not only checkpoints |
| Gateway refusal of an old `X-Lease-Generation` | Gateway stores the highest generation seen per thread and refuses lower ones, as Kleppmann describes |
| | Lease expiry on PostgreSQL `now()`, removing E2 gotcha 4's clock skew |
| | New test: the same process re-acquires its thread after a pause and its old-generation write is refused |
| | On refusal the stale run stops and discards its in-memory state |

### Changes to E5

| Keep | Change |
|---|---|
| `timers` table, `sync_timers`, keying by interrupt and round, SLA events, the nine tests | Extract `fire(timerId)` and an internal `POST /v1/timers/fire`; the poller calls the function |
| Database clock for due times | Replace the lock held for the step's duration with a claim (`claimed_generation`, `claimed_at`) fenced by E2b |
| | Cap retries of a breach resume that keeps failing (E5 gotcha), then journal it for manual handling |
| | Test: a duplicate and an early external `fire` both do nothing |

## Open questions for the maintainers

1. Fence check in the gateway: read the shared lease table, or keep its own highest-seen generation? Default: its own, so the gateway stays deployable apart.
2. May a deployment use an external scheduler (Cloud Tasks, EventBridge) at all? Default: not until one asks; the poller is the only scheduler shipped.
3. Lease clock: move expiry to the database clock in E2b? Default: yes.
4. Temporal oracle: write tests 9 and 10 and the documented-semantics suite now? Default: yes, 2–3 days, before the LangGraph adapter grows past slice 1.

## Sources

[^t-hist]: https://github.com/temporalio/temporal/blob/main/docs/architecture/history-service.md
[^t-act]: https://docs.temporal.io/activity-execution
[^t-forum]: https://community.temporal.io/t/activity-timeout-and-temporal-server-connectivity-issue/8869
[^t-timer]: https://docs.temporal.io/workflow-execution/timers-delays
[^cad]: https://cadenceworkflow.io/docs/concepts/activities
[^dbos-491]: https://github.com/dbos-inc/dbos-transact-java/issues/491
[^dbos-arch]: https://docs.dbos.dev/architecture
[^dbos-wf]: https://docs.dbos.dev/python/tutorials/workflow-tutorial
[^restate-arch]: https://docs.restate.dev/references/architecture
[^restate-timer]: https://docs.restate.dev/develop/python/durable-timers
[^restate-awk]: https://docs.restate.dev/develop/python/awakeables
[^inngest-exec]: https://www.inngest.com/docs/learn/how-functions-are-executed
[^inngest-idem]: https://www.inngest.com/docs/guides/handling-idempotency
[^adf-storage]: https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-azure-storage-provider
[^adf-38]: https://github.com/Azure/azure-functions-durable-extension/issues/38
[^adf-timer]: https://learn.microsoft.com/en-us/azure/azure-functions/durable/durable-functions-timers
[^sfn-cb]: https://docs.aws.amazon.com/step-functions/latest/dg/connect-to-resource.html
[^sfn-sts]: https://docs.aws.amazon.com/step-functions/latest/apireference/API_SendTaskSuccess.html
[^sfn-redrive]: https://docs.aws.amazon.com/step-functions/latest/dg/redrive-executions.html
[^lg-server]: https://docs.langchain.com/langsmith/agent-server
[^lg-blog]: https://www.langchain.com/blog/runtime-behind-production-deep-agents
[^lg-cron]: https://docs.langchain.com/langsmith/cron-jobs
[^lg-redis]: https://neuralware.github.io/posts/langgraph-redis/
[^kafka]: https://www.confluent.io/blog/transactions-apache-kafka/
[^kleppmann]: https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html
[^pgcron]: https://github.com/citusdata/pg_cron
[^pg-notify]: https://www.postgresql.org/docs/current/sql-notify.html
[^gct]: https://docs.cloud.google.com/tasks/docs/creating-http-target-tasks
[^gct-quota]: https://docs.cloud.google.com/tasks/docs/quotas
[^eb]: https://docs.aws.amazon.com/scheduler/latest/UserGuide/schedule-types.html
