# ADR-0015 Execution engine seam

Status: superseded in part on 2026-10-16: the owner removed Temporal, so no Temporal adapter will sit behind the seam; the engine is `ops_engine` on LangGraph and PostgreSQL (see `.codeloop/wiki/concepts/system-overview.md`). Earlier status: option, not decided. No ADR has been confirmed by the owner as of 2026-10-10; each one records the options, a scoring and a recommendation, and the build keeps a seam open so the choice can differ per enterprise deployment.

## Context

[ADR-0001](durable-execution-runtime.md) made self-hosted Temporal the only execution engine.
the owner ruled on 2026-10-10 that Temporal must be optional, because some banks will not approve a new
stateful server, and asked whether LangGraph or the OpenAI Agents SDK can take the engine role. Specs
[`14`](../../../.codeloop/wiki/concepts/runtime-service.md), [`15`](../../../.codeloop/wiki/concepts/agent-kernel.md) and
[`16`](../../../.codeloop/wiki/concepts/interpreter-and-nodes.md) are written in Temporal terms; what `16` needs from
any engine is the first column of the gap table below.

## Options

| Option | What it is | Facts (read 2026-10-10) |
|---|---|---|
| Temporal | Durable execution server; replays workflow code from history | Python SDK `temporalio` 1.34.0, 2026-09-30, MIT ([PyPI][pypi-temporal]). Server facts as in ADR-0001 |
| LangGraph on PostgreSQL | Graph library; state saved per thread by a checkpointer, in-process | `langgraph` 1.2.14, 2026-10-06, MIT ([PyPI][pypi-lg]). `PostgresSaver` in `langgraph-checkpoint-postgres` 3.1.2 ([PyPI][pypi-lgpg]). `interrupt()` needs a checkpointer and `thread_id`; resume with `Command(resume=...)`; the interrupted node restarts from its beginning, so code before `interrupt()` must be idempotent ([interrupts][lg-int]). Durability modes `exit`, `async`, `sync` per run ([checkpointers][lg-cp]). `RetryPolicy`, `TimeoutPolicy` and `error_handler` per node, announced 2026-06-04 ([fault tolerance][lg-ft]). No durable timers, no scheduled resume and no automatic restart of a crashed run found in the docs read |
| OpenAI Agents SDK | Agent-loop library: handoffs, guardrails, MCP, tracing | `openai-agents` 0.23.1, 2026-10-02, MIT ([PyPI][pypi-oai]). No engine of its own; durability comes from Temporal (GA for Python 2026-03-23), DBOS, Restate or Dapr integrations ([Temporal][t-oai], [DBOS][dbos-oai]). Tracing is on by default and exports to the OpenAI backend; off with `OPENAI_AGENTS_DISABLE_TRACING=1` or `set_tracing_disabled(True)` ([tracing][oai-trace]) |
| DBOS Transact | Durable workflows as a library over PostgreSQL | `dbos` 3.2.0, 2026-09-29, MIT ([PyPI][pypi-dbos]). Resumes an interrupted workflow from its last completed step; durable sleep stored in the database; workflow id is an idempotency key ([tutorial][dbos-wf]). Human waits and versioning of running workflows not read in this session (**unverified**) |

The OpenAI Agents SDK cannot be an engine: it has nothing to persist, time or supervise a run. It is
recorded as a kernel alternative under ADR-0014 (3.40 against Pydantic AI's 4.40). If adopted, tracing
is disabled at process start and model calls use Chat Completions via the key-and-budget service.

## The seam

The Runtime calls one `Engine` interface; the interpreter's node handlers call one `EngineContext`.
Neither names Temporal or LangGraph, so the catalogue (`16` §3) and the kernel (`15`) stay unchanged.
Child runs go through R1 with `parentRunId` on both engines (`16` 3.14).

| Interface | Operation | Temporal adapter | LangGraph-on-Postgres adapter |
|---|---|---|---|
| `Engine` | `start_run(planRef, runContext, key)` | Start `InterpreterWorkflow`, id = `runId` | Insert `engine_run` (unique `runId`), enqueue work; graph built from the plan at first pickup |
| `Engine` | `deliver_update(runId, name, payload, updateId)` → accepted or rejected | Temporal Update with validator | Under a per-run advisory lock: dedupe on `engine_update.update_id`, run the same validator on `get_state()`, then enqueue `Command(resume=...)` |
| `Engine` | `cancel`, `query`, `event_stream` | Cancel, Query, history plus journal | Flag plus `Command`; `get_state()`; journal rows (`16` 8.2) |
| `EngineContext` | `call(node, options)` with retry by side-effect class | Activity on `act-<tier>` | Node body under `RetryPolicy` for short retries; long backoff becomes a timer |
| `EngineContext` | `sleep_until`, `wait_for(updates, timeout)` | Durable timer, Update handler | Row in `timers`, then `interrupt()`; a poller resumes due timers |
| `EngineContext` | `now()`, `uuid()` | `workflow.now()`, `workflow.uuid4()` | Clock and `uuid4` recorded in state before use |

### What LangGraph lacks against `16`, and what the adapter adds

| Requirement | LangGraph alone | Adapter adds | Residual gap |
|---|---|---|---|
| Durable timers, SLA, escalation | None | `timers(run_id, timer_id, due_at, kind)` table and a poller per tier using `FOR UPDATE SKIP LOCKED` that resumes the thread | Timer accuracy is the poll interval (proposed 5 s) |
| Retries and supervision | Per-node `RetryPolicy`; nothing restarts a crashed run | Per-node retry from the plan's class; a lease on each work row, and an expired lease is re-picked and resumed from the last checkpoint | We own the supervisor code |
| Idempotency | None | Keys from `15` and `16` (`{runId}:{nodeId}:{iteration}`, `run_id:turn_id:step:ordinal`), unchanged | Same as Temporal |
| Crash mid-activity | Node re-runs from its start | `durability="sync"`; a journal row before and after each side-effecting node; the kernel step ledger stored in a table instead of heartbeat details | Every side-effecting node must be idempotent or reconciled, as `16` 7.1 already demands |
| Worker scaling, tiers | One process calls `invoke` | `engine_work` queue table; worker pools per tier poll their tier with SKIP LOCKED; a Postgres role per tier with row-level security in place of Temporal's poll authoriser | No schedule-to-start metrics unless we emit them |
| Versioning of running instances | None for code | Plan-by-digest covers definitions. Each run records its `engineBuild`; workers pick only rows for their build, so old builds drain like Pinned runs | No ramp, no `patched()`; an emergency fix to a draining build needs a hand migration |
| Replay | Checkpoint history (`get_state_history`) | Resume corpus: restore recorded checkpoints and resume them on the new build with recorded activity fakes | Weaker than deterministic replay: it proves a run resumes, and cannot prove the command sequence is unchanged |
| History size | Checkpoints accumulate | Prune checkpoints of closed runs after the journal is written | None of Temporal's 51,200-event limit, so `16` test 14 does not apply |

### Scoring

Criteria and weights are ADR-0001's; the Temporal row is unchanged from it. Where a bank refuses the
server Temporal is unavailable, which no score captures.

| Option | Durab. 13 | Determ. 8 | HITL 13 | Versioning 13 | Security 9 | On-prem 9 | Licence 9 | Talent 4 | Connectors 4 | Fit 4 | Marginal 14 | **Total** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Temporal adapter | 5 | 5 | 5 | 5 | 4 | 4 | 4 | 4 | 2 | 5 | 4 | **4.43** |
| DBOS adapter (**unverified** HITL, versioning) | 4 | 3 | 3 | 3 | 4 | 5 | 4 | 2 | 1 | 4 | 3 | **3.41** |
| LangGraph-on-Postgres adapter | 3 | 2 | 4 | 3 | 4 | 5 | 4 | 4 | 3 | 4 | 2 | **3.35** |
| LangGraph + checkpointer, no adapter (ADR-0001) | 3 | 2 | 4 | 2 | 3 | 4 | 4 | 4 | 3 | 4 | 2 | **3.04** |

The adapter lifts versioning (build-pinned work rows), security (no new server, a Postgres role per
tier) and on-prem (PostgreSQL only). Durability stays at 3 because timers, leases and supervisor are
our code. DBOS scores higher on paper and is the strongest challenger for engine B (open question 2).

### LangGraph for both engine and agent loop

LangGraph can also run the agent loop (`create_react_agent`, deprecated since 1.0 for
`langchain.agents.create_agent`, [migration][lg-mig]). We keep the Pydantic AI kernel under both
engines: the kernel must behave identically on Temporal, it owns no persistence (`07` CD-2) while
LangGraph interrupts need the checkpointer, LangGraph has no AI SDK UI stream encoder, and
`create_agent` adds `langchain`. The kernel's `Interrupt` maps to the engine's human step on both.

## Decision

Two supported engines behind one seam, chosen per deployment (`engine: temporal | langgraph_pg`):
**Temporal**, preferred wherever the bank allows the server, and **LangGraph on PostgreSQL**,
in-process with no extra server. The interpreter is written against `EngineContext`;
`16` §1.1 determinism rules still bind it, because the Temporal adapter replays it.

**Phase 1 ships the seam and the LangGraph-on-Postgres adapter first.** Slice 1 already needs
PostgreSQL and nothing else, so every bank can run it, and building the weaker engine first forces
the seam to name timers, updates and leases explicitly instead of inheriting them from Temporal. The
Temporal adapter follows before the first production deployment that allows the server. Temporal
first would ship less code, and would let Temporal-only behaviour (heartbeat ledger, Pinned builds)
leak into the interpreter before the seam exists.

Every plan must obey these rules to run on both engines; the compiler enforces them:

| Rule | Why |
|---|---|
| Every side-effecting node is idempotent by key, or is a non-idempotent `write` with one attempt and a reconciliation read (`16` 7.1) | LangGraph re-runs an interrupted node from its start |
| No engine-specific node settings: no task queue names, Temporal timeouts or LangGraph policies in the definition; the compiler derives them from side-effect class and tier | A plan is portable between deployments |
| Waits are expressed only as `delay`, `wait for event` or `human step` | These are the only waits both adapters implement |
| Child workflows start through R1 (`16` 3.14) | Neither adapter needs engine-level child runs |

Both adapters must pass one conformance suite from `16` §9. Test 1 there (replay) stays engine-specific:
deterministic replay on Temporal, the resume corpus on LangGraph.

| # | Test (`16` §9 number) |
|---|---|
| 1 | Crash mid-write: kill after the gateway accepts; the stub records one call (2) |
| 2 | Duplicate trigger: R1 twice with one key returns the first run (3) |
| 3 | Stale decision: the old token's update is rejected by the validator (4) |
| 4 | SLA timeout with `onTimeout: reject` rejects; no timeout path approves (7) |
| 5 | Customer reply cancels and restarts the SLA timers with the extended due time (8) |
| 6 | Retry budget exhausted lands in manual handling with the error (9) |
| 7 | Kernel interrupt survives a wait; the agent retry replays the ledger with no second model or tool call (12, 12a) |
| 8 | R9 lets an in-flight write finish and marks the remaining nodes `skipped` (13) |

## Consequences

### Strongest counter-argument and our answer

**"Two engines doubles the surface: two sets of bugs, two runbooks."** True, and the cost is
ongoing; the alternative is losing every bank that refuses the server. Catalogue, kernel, compiler,
journal and console are shared; engine code is two adapters plus the timer poller and lease
supervisor, and the conformance suite runs on both in CI. If DBOS wins open question 2, it replaces
LangGraph rather than adding a third engine.

What would change this decision: no target bank refuses Temporal (drop engine B); the DBOS spike passes the conformance suite with
less adapter code (DBOS replaces LangGraph as engine B); LangGraph's open-source library gains durable
timers and crash supervision (delete our poller and supervisor).

ADR-0001's status line gains: "Superseded in part by [ADR-0015](execution-engine-seam.md):
Temporal is the preferred engine, no longer the only one; LangGraph on PostgreSQL is a second
supported engine behind the same seam, chosen per deployment."

## LangGraph adapter dependencies

| Package | Version | Licence | Why | Sends data out |
|---|---|---|---|---|
| `langgraph` | 1.2.14 | MIT | Graph, `interrupt`, `Command` | None found in docs read (**unverified**) |
| `langgraph-checkpoint`, `-postgres` | 4.2.0, 3.1.2 | MIT | `PostgresSaver` | No |
| `psycopg`, `psycopg-pool` | 3.3.6, 3.3.3 | LGPL-3.0-only | Required by the checkpointer (psycopg 3) | No |
| `langchain-core` | 1.6.9 | MIT | Required by `langgraph` | Pulls `langsmith` 0.14.7 (MIT), which sends traces only when `LANGSMITH_TRACING=true` ([LangSmith][ls-trace]); set it `false` explicitly |
| `langgraph-sdk`; `ormsgpack`, `orjson`, `xxhash` | 0.4.6; 1.12.2, 3.13.0, 4.0.1 | MIT; Apache-2.0/MIT, MPL-2.0 with Apache-2.0/MIT, BSD-2 | Server client (required, unused); serialisation, hashing | Only if the client is called; no |

LGPL: importing psycopg unmodified is permitted in a proprietary product; obligations apply if we
ship a modified copy (legal to confirm). Default-deny egress (ADR-0004) catches telemetry we missed.

## Open questions for the owner

1. Which engine does the first bank get? Default: LangGraph on PostgreSQL until it approves Temporal.
2. Spike DBOS against the conformance suite before the LangGraph adapter grows past slice 1? Default: yes, time-boxed to one week, because it scores higher and ships timers and recovery we would otherwise write.
3. Timer poll interval for SLA timers. Default: 5 s; SLAs are hours.
4. May one deployment switch engines with runs open? Default: no; drain first.

## Sources

[pypi-temporal]: https://pypi.org/project/temporalio/
[pypi-lg]: https://pypi.org/project/langgraph/
[pypi-lgpg]: https://pypi.org/project/langgraph-checkpoint-postgres/
[pypi-oai]: https://pypi.org/project/openai-agents/
[pypi-dbos]: https://pypi.org/project/dbos/
[lg-int]: https://docs.langchain.com/oss/python/langgraph/interrupts
[lg-cp]: https://docs.langchain.com/oss/python/langgraph/checkpointers
[lg-ft]: https://www.langchain.com/blog/fault-tolerance-in-langgraph
[lg-mig]: https://docs.langchain.com/oss/python/migrate/langgraph-v1
[t-oai]: https://docs.temporal.io/develop/python/integrations/openai-agents
[dbos-oai]: https://docs.dbos.dev/integrations/openai-agents
[dbos-wf]: https://docs.dbos.dev/python/tutorials/workflow-tutorial
[oai-trace]: https://openai.github.io/openai-agents-python/tracing/
[ls-trace]: https://docs.langchain.com/langsmith/trace-with-langchain
