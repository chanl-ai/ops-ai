# 16 Interpreter and nodes

Status: draft for review. Binding inputs: ADR-0001, ADR-0002, ADR-0003, ADR-0004, ADR-0005 and
ADR-0006 in `docs/architecture/decisions/`; `docs/architecture/overview.md`; `docs/architecture/service-map.md`;
specs `14` (Runtime), `15` (agent kernel: 2.2, 4.5, 4.7, 5), `01` (Agent Builder) and `04` 5.2. The task named `app/workflows/[id]/**` for the palette; that page
renders `WorkflowEditor` (`apps/console/src/app/workflows/[id]/page.tsx:148`), whose palette is
`NODE_KINDS` in `apps/console/src/components/workflows/node-types.ts`, so node citations use that file.
File references are relative to the ops-ai repository root.

## Summary

The interpreter is one Temporal workflow type, `InterpreterWorkflow(planRef)`, that executes any
compiled execution plan. The control plane compiles a published definition into a plan whose nodes
carry resolved pins and activity options, addressed by its own digest. Each node kind has a
side-effect class that sets its retry policy and idempotency rule, and each node execution writes one
journal row. Human steps are Temporal Updates with validators plus durable timers, so a run waiting
days holds no worker. A run pins `(versionNumber, definitionDigest, planDigest)` for life; interpreter
code is versioned by Worker Versioning with Pinned runs (ADR-0004), and patching is used only on the
continue-as-new upgrade path and for emergency fixes.

## 1 What the interpreter is

`InterpreterWorkflow` is the only workflow type on interpreter workers (`docs/specs/runtime-service.md:76`).
Its input is `planRef = {planDigest, runContext}`, where `runContext` holds R1's start record:
`runId`, `workflowId`, `versionNumber`, `definitionDigest`, `environment`, `mode`, `subject`, `trigger`,
`inputRef`, `parentRunId?`, `evalSeed?` (`docs/specs/runtime-service.md:110`). It loads the plan and
walks edges from the entry node until an `end` node or cancellation.

### 1.1 Determinism rules

The interpreter is the platform's only Temporal workflow code (`docs/architecture/overview.md:142`).
Review, the Temporal Python sandbox and replay tests enforce these rules.

| Rule | How it is met |
|---|---|
| No I/O in workflow code | Plan load, every gateway call, case call, file write and journal write is an activity. The plan is loaded by a local activity at start, so its content enters history once and replay reads it from there |
| All side effects in activities | Node handlers in workflow code only evaluate CEL, choose edges and schedule activities, timers and child workflows |
| Time | `workflow.now()` for timestamps; durable timers for every wait. CEL expressions that need the time receive `now` as a bound variable set from `workflow.now()` |
| Randomness and ids | `workflow.uuid4()` and `workflow.random()`. The task mentioned `side_effect`; the Python SDK has no `side_effect` call as far as this draft knows, and these two functions serve the same purpose (Python SDK API names not re-read, **unverified**) |
| Expression evaluation | CEL (`docs/specs/agent-builder.md:374`) is deterministic and non-Turing-complete, so it runs inside workflow code. The CEL library must be passed through the sandbox and pinned per interpreter build, because a library upgrade that changes a result is a non-deterministic change |
| Iteration order | Plans store nodes, edges and ports as ordered arrays; handlers never iterate over sets or unordered maps |
| Code changes | A change that alters the command sequence for an existing plan ships as a new Worker Deployment Version (section 5) |

### 1.2 Why one workflow type

One type for every definition is ADR-0001's decision
(`docs/architecture/decisions/durable-execution-runtime.md:85`). Its cost is that one
interpreter bug affects every workflow, which the replay gate in section 9 guards against.

| Concern | One interpreter type | One workflow type per definition |
|---|---|---|
| Who writes deterministic code | The platform team, once | Every workflow becomes generated or hand-written workflow code |
| Version of a running instance | The run carries `planDigest`; a new definition version is data and never touches the replayed code (`docs/architecture/overview.md:142`) | Each definition version is a code change; running instances need patching or a new type name per version |
| Worker deployments | One build per tier per Worker Deployment Version (`docs/specs/runtime-service.md:76`) | Workers must register every type ever published and keep old ones while runs drain |
| Replay testing | One replay corpus covers every workflow (`docs/specs/runtime-service.md:457`) | A corpus per generated type |

## 2 The execution plan

### 2.1 What the compiler emits

The compiler runs in the control plane (`docs/architecture/overview.md:137`). Its input is a fully
pinned definition (`docs/specs/agent-builder.md:118`); a template-based definition is first
expanded into a graph (`docs/architecture/decisions/workflow-definition-format.md:60`).

| Plan field | Content |
|---|---|
| `planSchemaVersion` | Integer; section 2.3 |
| `workflowId`, `versionNumber`, `definitionDigest` | Copied from the version; the plan is tied to one definition |
| `effectiveTier` | From `01` 5.2; selects task queues |
| `entry` | Node id of the trigger node |
| `nodes[]` | `{id, kind, kindVersion, label, settings, pins, ports[], activity?, sideEffect, onError?}`; `settings` is validated against the node type's `configSchema` (`docs/specs/agent-builder.md:179`) and has every reference resolved to a pinned version |
| `edges[]` | `{from, port, to}`; ports are named (`yes`, `no`, intent ids, `approved`, `rejected`, `timeout`, `error`) |
| `humanStepPolicies[]` | Copied from the definition (`docs/specs/agent-builder.md:194`), with CEL conditions pre-parsed |
| `manualHandling` | `{queueId, notifyGroup}` from the template (`docs/specs/agent-builder.md:160`) |
| `limits` | `maxSteps` (proposed 500), `maxLoopItems`, `maxParallel`, `maxWaitDays` |

Per-node `activity` options:

| Option | Rule |
|---|---|
| `name` | The activity type for the node kind (section 3) |
| `taskQueue` | `act-<tier>`, `agent-<tier>` or the interpreter's own queue for local activities (`docs/specs/runtime-service.md:77`). The tier is the plan's `effectiveTier`. A plan holds no environment name, because promotion copies it by digest with no rebuild (`docs/architecture/decisions/deployment-tenancy-and-promotion.md:56`); the environment comes from the Temporal namespace and the run context |
| `startToClose`, `scheduleToClose`, `heartbeat` | Defaults per kind, overridable per node within a cap the node type sets |
| `retry` | From the side-effect class (section 7.1); the compiler refuses an override that adds attempts to a non-idempotent write |
| `idempotency` | Template string resolved at run time: `{runId}:{nodeId}:{iteration}` for reads and agents, `{runId}:{actionId}` for drafted actions (`docs/specs/agent-builder.md:208`) |

### 2.2 Digest, storage and fetch

`planDigest` is SHA-256 over the canonical JSON of the plan, canonicalised as the definition is
(`docs/specs/agent-builder.md:110`), and recorded on the version (`docs/specs/agent-builder.md:117`).
The control plane stores plans by digest; the Runtime fetches with `getPlan` and verifies the digest
(`docs/specs/runtime-service.md:172`). In the interpreter the fetch is a local activity `load_plan`
at run start, so the plan enters history once, encrypted, and replay reads it from history. Workers keep
a parsed copy by digest, which is what spec 14 calls "plan cached by digest in memory"
(`docs/specs/runtime-service.md:76`). The compiler refuses plans above 256 KB (proposed) to stay
below Temporal's payload limits (not re-read, **unverified**).

### 2.3 Schema version handling

| Case | Behaviour |
|---|---|
| Each interpreter build | Declares the range of `planSchemaVersion` it executes |
| Compiler emits a version the production build does not support | The registry refuses the pointer move with 422 and names the build range (proposed) |
| Run starts with an unsupported plan | `load_plan` raises a non-retryable `plan_unsupported`; the run ends `failed` before any step, R1 has already returned, and an alert goes to the platform team |
| New schema version | Additive changes keep the version; a change in meaning bumps it. Old versions stay supported while any pointer or open run uses them |

## 3 Node catalogue

The mock palette has 28 kinds (`apps/console/src/components/workflows/node-types.ts:84`); several are
configurations of one interpreter kind (`docs/architecture/decisions/durable-execution-runtime.md:101`).
"Mock" means a palette entry exists at the cited line; "new" means none exists. Side-effect classes
are `01` 4.6's (`docs/specs/agent-builder.md:188`), with `money` for `money_movement`. Run sheet
rows name a `RunStep.kind` (`apps/console/src/lib/types/domain.ts:350`); 3.16 lists the new values.

### 3.1 trigger

| Aspect | Rule |
|---|---|
| Mock | Mock: `chat`, `api`, `email`, `event`, `schedule`, `batch` (`node-types.ts:86`–`:91`). New: `mcp` and `agent_tool` sources |
| Settings | `source` (`email`, `schedule`, `api`, `chat`, `event`, `batch`), `inputSchema` (JSON Schema of the run input). The mailbox belongs to the deployment and is not stored on the node (`docs/specs/agent-builder.md:383`) |
| Activity | None. The run input arrives in `runContext.inputRef`; the trigger node validates it against `inputSchema` inside a `load_input` activity when the input is a file reference |
| MCP and agent tool | These are channels of a published workflow, created by the registry on exposure (`docs/specs/data-and-ai-gateways.md:194`). They start a run with R1 and the trigger node sees `trigger.channel` = `mcp` or `workflow_tool`. No palette entry is needed |
| Outputs | `input` (reference), `trigger` facts |
| Side effect, idempotency | `none`; R1 de-duplicates on `trigger.key` (`docs/specs/runtime-service.md:110`) |
| Failure | Schema mismatch is non-retryable and goes to `onError` |
| Run sheet | Kind `trigger`; detail shows the channel and, for child runs, "Started by agent <name>" (`apps/console/src/lib/api/mock/history.ts:134`) |

### 3.2 agent

| Aspect | Rule |
|---|---|
| Mock | Mock: `agent` (`node-types.ts:93`); `prompt` (`:94`), `classify` (`:95`) and `extract` (`:96`) are configurations of this kind. New: `draft_action` configuration (P2, `docs/specs/agent-builder.md:410`) |
| Settings | `agent{agentId, version}`, `mode` (`turn`, `classify`, `extract`, `draft`), `inputBindings` (CEL from run variables), `outputSchema`, for `classify` the labelled `paths[]` and `confidenceThreshold`, for `draft` the intent's `actions[]` |
| Activity | `agent_turn` on `agent-<tier>`; runs one kernel turn on the agent-block host. Input is a `TurnRequest` with `input: NodeInput{fields, instruction?}`, `turn_id` = the step id, and `resume`/`ledger` when set (`docs/specs/agent-kernel.md:64`, `:78`, `:79`) |
| Inputs, outputs | Output is a `TurnResult` (spec 15 §2.2, `docs/specs/agent-kernel.md:82`): `status` (`completed`, `interrupted`, `stopped`, `failed`), `stop_reason`, `parts`, `tool_calls[]`, `citations[]`, `no_answer`, `usage`, `interrupt`, `ledger`, `error` |
| Side effect, idempotency | `read` for the node itself. Tool calls inside the turn use the kernel's key `run_id:turn_id:step:ordinal`; writes use `runId:actionId`, with `actionId` derived from that key, so a retry cannot double-post (spec 15 §4.5, `docs/specs/agent-kernel.md:257`). A write returns `gated` and ends the turn with an approval interrupt (`docs/specs/runtime-service.md:197`) |
| Retry | The activity records the kernel's `StepLedger` as Temporal heartbeat details on each `sink.commit`. A retried attempt passes it back as `TurnRequest.ledger`, and the kernel replays committed model and tool steps without calling them again; only the step in flight at the crash is re-requested (spec 15 §4.5, `docs/specs/agent-kernel.md:256`, `:261`) |
| Interrupt handling | `status: interrupted` completes the activity with `Interrupt{interrupt_id, kind (approval, question, handoff), needed, pending_call?, question?, ledger}` (spec 15 §5, `docs/specs/agent-kernel.md:300`). The interpreter turns it into a human step (3.10): for `approval`, it attaches `pending_call` to the case as the drafted action and waits on R7 `actionDecided`; `question` and `handoff` become a manual human step on the case (`docs/specs/agent-kernel.md:351`). It then schedules a second `agent_turn` with `resume: Resume{interrupt_id, decision (approved, rejected, answered, handed_off), approval_token?, reason?, answer?}` and the interrupt's ledger (`docs/specs/agent-kernel.md:315`). On `approved` the resumed turn itself sends the stored payload with the token and the same idempotency key (`docs/specs/agent-kernel.md:324`) |
| Failure | By spec 15's error classes (§4.7, `docs/specs/agent-kernel.md:282`): `model_transient`, `gateway_degraded` and `internal` retry with the ledger (7.1); `model_denied`, `reconciliation` and assembly errors never retry. Past the budget, or on a non-retryable `failed`, a `classify` node routes to the fallback queue (`docs/specs/agent-builder.md:294`) and other modes go to `onError` |
| Run sheet | Kind `agent`; detail shows the chosen intent and confidence, or the drafted action count, plus cost |

### 3.3 tool

| Aspect | Rule |
|---|---|
| Mock | Mock: `tool` (`node-types.ts:113`). `http` (`:114`) is removed from the palette (`docs/specs/agent-builder.md:393`) |
| Settings | `module{name, version}`, `operation`, `inputBindings` (CEL), `actionId?` for writes |
| Activity | `gateway_call` on `act-<tier>`; MCP `tools/call` to the data gateway with the run context token (`docs/specs/runtime-service.md:192`) |
| Side effect | From the module operation's manifest: `read`, `write` or `money` |
| Writes | A write or money node runs only with an approval token for the exact payload. The compiler refuses a plan where a write node is reachable without a preceding human step or a policy approval rule covering it (`docs/specs/agent-builder.md:335`) |
| Idempotency | Reads `{runId}:{nodeId}:{iteration}`; writes `{runId}:{actionId}`; modules that cannot accept a key run at most once plus a reconciliation read (`docs/architecture/overview.md:290`) |
| Failure | `deny` never retries; `gateway_degraded` retries then goes to manual handling (`docs/specs/runtime-service.md:209`); an expired approval token returns the action to `drafted` and re-opens the human step (`docs/specs/agent-builder.md:439`) |
| Run sheet | Kind `tool` for reads, `action` for writes; detail shows module, operation and result status; `gatewayCallIds` on R5 |

### 3.4 knowledge

| Aspect | Rule |
|---|---|
| Mock | Mock: `knowledge` (`node-types.ts:98`–`:112`) with `queryMode`, `filters`, `answerShape` |
| Settings | `modules[{moduleName, version}]` (pinned), `query` (CEL), `queryMode`, `filters` (CEL per line), `answerShape` (`chunks` or `answer`), `topK` |
| Activity | `knowledge_search` on `act-<tier>` through the data gateway (`docs/specs/runtime-service.md:213`) |
| Outputs | Passages with citations (section, page, version) or `noAnswer` |
| Side effect, idempotency | `read`; `{runId}:{nodeId}:{iteration}` |
| Failure | `noAnswer` is a normal result and follows the default edge; transport failures as 3.3 |
| Run sheet | New `RunStep.kind` `knowledge`; detail shows passage count and top citation |

### 3.5 condition

| Aspect | Rule |
|---|---|
| Mock | Mock: `condition` (`node-types.ts:123`) |
| Settings | `expr` (CEL boolean over run variables) |
| Activity | None; evaluated in workflow code |
| Ports | `yes`, `no` |
| Side effect | `none`; deterministic, so replay gives the same branch |
| Failure | A CEL runtime error (missing field, type error) is non-retryable and goes to `onError`; the server check catches most of these at publish |
| Run sheet | New `RunStep.kind` `logic`; detail shows the expression and the branch taken; duration 0 |

### 3.6 switch on classification

| Aspect | Rule |
|---|---|
| Mock | Mock: `switch` (`node-types.ts:124`) and the labelled paths of `classify` (`:95`) |
| Settings | `expr` (CEL returning a value), `cases[{value, port}]`, `default` port. In the email template the value is the classified intent id and the cases are the intents |
| Activity | None |
| Rule | Classification selects an intent, queue and case type and nothing else; a switch port can never skip a human step that the plan requires for a write on that path (`docs/specs/agent-builder.md:296`) |
| Side effect, failure | As 3.5 |
| Run sheet | Kind `logic`; detail shows the value and the case matched |

### 3.7 loop and map

| Aspect | Rule |
|---|---|
| Mock | Mock: `loop` with "For each" only (`node-types.ts:125`). New: `concurrency`, `maxItems` and the body subgraph |
| Settings | `items` (CEL list), `body` (entry node id of a subgraph that ends in a `loop_end`), `concurrency` (1–20, default 1), `maxItems` (cap, default 100), `collect` (output variable) |
| Execution | The interpreter schedules body executions with at most `concurrency` in flight, each with its own `iteration` index in idempotency keys. Above 50 items (proposed) the body runs as child workflows, so one run's history stays under the event limit (`docs/architecture/decisions/deployment-tenancy-and-promotion.md:30`) |
| Side effect | The highest class in the body |
| Failure | Per-item failure follows the body's `onError`; the loop records failed items and continues unless `stopOnError` is set |
| Run sheet | Kind `logic` with item counts; body steps listed per iteration |
| Phase | Later (`docs/specs/agent-builder.md:402`) |

### 3.8 delay

| Aspect | Rule |
|---|---|
| Mock | Mock: `wait` with a duration (`node-types.ts:126`) |
| Settings | `duration` or `until` (CEL timestamp), `businessHours` with the queue calendar |
| Activity | None; a durable timer. Business-hours deadlines are computed by an activity against the calendar, then the timer is set |
| Side effect, failure | `none`; no failure beyond cancellation |
| Run sheet | New `RunStep.kind` `wait`; detail "Waiting until <time>" |
| Phase | Later |

### 3.9 wait for event

| Aspect | Rule |
|---|---|
| Mock | Mock: `wait` "or event" (`node-types.ts:126`) and `ask` (`:120`), which drafts a question then waits |
| Settings | `event` (`customerReplied` in phase 1), `timeout`, `onTimeout` port |
| Execution | Registers an Update handler for the event and a timer. For `ask`, the case moves to `waiting_customer` and the SLA clock pauses (`docs/specs/agent-builder.md:458`); the reply arrives as R7 `customerReplied` from mailbox intake via the case service (`docs/specs/runtime-service.md:116`) |
| Side effect | `none` for the wait; the question itself is a `send_reply` drafted action (3.13) |
| Failure | Timeout follows `onTimeout`, which in the email template closes the case "no reply" |
| Run sheet | Kind `wait`; detail "Waiting for customer reply" |
| Phase | 1, template only (`docs/specs/agent-builder.md:398`) |

### 3.10 human step

| Aspect | Rule |
|---|---|
| Mock | Mock: `approval` (`node-types.ts:118`), `two-person` (`:119`), `handoff` (`:121`). New: `per_action_approval` (P3, `docs/specs/agent-builder.md:411`) |
| Settings | `policyId` (a `HumanStepPolicy`, `docs/specs/agent-builder.md:194`), `mode` (`approve_actions`, `review`, `manual`), `actions` (for `approve_actions`, the drafted action ids from a prior `draft` agent node) |
| Activities | `create_decision_tasks` (case or review service), then a wait (section 4), then `sla_event` on timer fire |
| Ports | `approved`, `rejected`, `timeout`; for `approve_actions` each approved action continues to its execute node and the step completes when no action is pending |
| Side effect, idempotency | `write` to the case service only; `create_decision_tasks` keyed `{runId}:{nodeId}:{iteration}`, so a retry returns the same tasks |
| Failure | Case service down: retry, then wait on a `case_unavailable` timer hourly (`docs/specs/runtime-service.md:303`) |
| Run sheet | Kind `review`; status `waiting` with "Paused for <group>" (`apps/console/src/lib/api/mock/history.ts:96`) and the review link (`apps/console/src/components/workflows/run-trace.tsx:56`) |

### 3.11 gate

| Aspect | Rule |
|---|---|
| Mock | New. The mock has gate policies as data (`apps/console/src/lib/types/domain.ts:211`) and draws them on review nodes; there is no palette entry |
| Purpose | Decides whether a human step is required for the current payload. It evaluates the `condition` of each applicable policy and either issues a policy approval or routes to a human step |
| Settings | `policyIds[]`, `subject` (the action or turn output it evaluates) |
| Activity | CEL conditions run in workflow code. A policy approval token for `autoApproveBelow` is issued by the case service through an `issue_policy_approval` activity, because only the case service signs tokens (`docs/specs/agent-builder.md:430`) |
| Ports | `needs_person`, `approved_by_policy` |
| Rules | Policy approval is refused for `money` and for tiers above `medium`, and is never issued on an SLA timeout (`docs/specs/agent-builder.md:430`) |
| Run sheet | Kind `logic`; detail "Approved by policy vN" or "Needs <group>" |

### 3.12 case (open case)

| Aspect | Rule |
|---|---|
| Mock | New: P1 `open_case` (`docs/specs/agent-builder.md:409`) |
| Settings | `route` (from the intent route: `queueId`, `priority`, `slaHours`, `businessHours`), `fields` binding |
| Activity | `open_case` then `attach_actions` on `act-<tier>` (`docs/specs/runtime-service.md:286`) |
| Outputs | `caseId`, `queue`, `slaDueAt`, `warnAt`; the interpreter starts the SLA timers from these |
| Side effect, idempotency | `write` to the case service; keyed `{runId}:{nodeId}` so a retry finds the same case |
| Run sheet | New `RunStep.kind` `case`; detail shows queue and SLA due time |

### 3.13 send reply and draft

| Aspect | Rule |
|---|---|
| Mock | Mock: `send-email` (`node-types.ts:130`) and `reply` (`:129`) |
| Settings | `module` `m365-mail` at a pinned version, operation `mail.send_reply`, `actionId`, `fromAddress` (approved sender) |
| Execution | Always a drafted action: the drafting agent produces the MIME payload, a human step or policy approval issues a token bound to its hash, then `gateway_call` sends it (`docs/specs/agent-builder.md:406`) |
| Side effect, idempotency, failure | `write`, approval-only; `{runId}:{actionId}`; failures as 3.3 writes |
| Run sheet | Kind `action`; detail shows recipient and "Approved by <name>" or "Approved by policy vN" |
| Chat `reply` | Phase 2; returns the turn output on the triggering chat channel and has no gateway call |

### 3.14 child workflow

| Aspect | Rule |
|---|---|
| Mock | Mock: `subworkflow` "Calls another workflow and waits" (`node-types.ts:116`). This spec changes the default to start and continue, matching spec 14's child-run rule (`docs/specs/runtime-service.md:62`) |
| Settings | `workflowId` (resolved at run time through that workflow's live pointer, as for workflow tools), `inputBindings`, `wait` (default `false`) |
| Activity | `start_child_run` on `act-<tier>`: calls R1 with `parentRunId`, `parentStepId`, so the child is an ordinary run with its own identity, pins and tier queue. It is not a Temporal child workflow, because the child may run on a different tier queue and must outlive the parent |
| Outputs | `childRunId`, initial status |
| Side effect, idempotency | `write` (starting a run); R1 key = `{parentRunId}:{nodeId}:{iteration}` |
| Failure | R1 503 retries; a refused start (child paused or archived) goes to `onError` |
| Run sheet | New `RunStep.kind` `child_run`; detail links the child run, as `AgentTestTurn.startedRuns` does (`apps/console/src/lib/types/domain.ts:387`) |
| Phase | Later as a node; workflow tools called by agents start child runs in phase 1 (`docs/specs/runtime-service.md:478`) |

### 3.15 end and on error

| Aspect | Rule |
|---|---|
| Mock | Mock: `end` (`node-types.ts:131`) and `error` "On error" (`:132`) |
| Settings | `outcome` label |
| Execution | `end` completes the run with the outcome and a final `close_case` when the plan opened a case and no action is pending. `On error` is the target of every node's `onError`; in templates it leads to the manual-handling human step (`docs/specs/agent-builder.md:160`) |
| Run sheet | Kind `end`; run status `completed`, or `failed` when the outcome came through `On error` with no human completion |

### 3.16 Not in this catalogue and contract changes

`set` (`node-types.ts:127`) is a CEL assignment in workflow code with no activity, kind `logic`.
`code` (`:115`) and `batch` (`:91`) are later (`docs/specs/agent-builder.md:394`). `RunStep.kind`
gains `knowledge`, `case`, `child_run` (spec 14 contract change 4,
`docs/specs/runtime-service.md:157`) and, from this spec, `logic` and `wait`, which the run trace
icon map needs (`apps/console/src/components/workflows/run-trace.tsx:24`).

## 4 Human steps in detail

### 4.1 Update with a validator

A wait is a Temporal Update handler plus durable timers. Spec 14 already routes decisions through R7
as Updates (`docs/specs/runtime-service.md:116`); this section states why.

| Property | Update | Signal |
|---|---|---|
| Caller learns acceptance | Yes: the validator accepts or rejects before anything is written to history, and the case service's outbox row can be marked delivered or rejected | No: a signal is accepted whatever the run's state, and the caller cannot tell a stale decision from a used one |
| De-duplication | Update id = outbox row id; a re-delivery returns the first result | Needs a hand-built seen-set in workflow state |
| Stale decisions | Validator rejects a decision for an action that is no longer pending, or for a superseded payload hash | Must be handled after it is recorded |
| Cost | Requires the run to be reachable; when Temporal is down the case outbox holds it (`docs/specs/agent-builder.md:450`) | Same |

The validator checks only facts in workflow state: the `actionId` belongs to this step, the action is
pending, the token's `payloadHash` equals the hash recorded when the action was drafted, the token's
`approvers[]` count meets the policy's `requiredApprovals`, and no approver equals the run's `subject`
when the subject is a person. It does not verify the token signature, because that needs keys and is
the data gateway's check (`docs/specs/agent-builder.md:209`).

### 4.2 What the decision task carries

Created by `create_decision_tasks` as kind `case_action` for case actions or `gate_approval` for
review gates (`docs/specs/agent-builder.md:195`):

| Field | Source |
|---|---|
| `subjectRef{runId, stepId, caseId}` | Run context and the case node output |
| `approverGroup`, `requiredApprovals`, `slaHours`, `onTimeout`, `escalateTo` | The `HumanStepPolicy` in the plan |
| `body` | Action payload by `fileId`, `payloadHash`, citations, the model's reason; for a kernel `Interrupt`, its `needed` text and `pending_call` (`docs/specs/agent-kernel.md:305`) |
| `workflowId`, `versionNumber`, `risk` | Plan |

### 4.3 How the approval token reaches the tool activity

1. The case service signs the token on approval and sends R7 `actionDecided` with it
   (`docs/specs/runtime-service.md:292`).
2. The Update handler stores `{actionId → token}` in workflow state. The payload codec encrypts it in
   history (`docs/architecture/decisions/deployment-tenancy-and-promotion.md:30`).
3. The interpreter schedules `gateway_call` for that action with the token as an argument.
4. The activity sends the exact payload by reference and the token header to the data gateway, which
   checks hash, expiry, scope and entitlement (`docs/architecture/overview.md:270`).
5. The interpreter drops the token from state once the activity completes.

If the activity runs after the 24-hour expiry, the gateway refuses, the action returns to `drafted`
and the human step re-opens for that action (`docs/specs/agent-builder.md:439`).

### 4.4 SLA timer and escalation

| Event | Interpreter behaviour |
|---|---|
| Case routed | Start two timers from `warnAt` (80%) and `slaDueAt` (`docs/specs/agent-builder.md:210`) |
| Warn timer fires | `sla_event(warn)` activity; the case service notifies the queue lead |
| Breach timer fires | `sla_event(breach)` returns the `onTimeout` outcome (`docs/specs/runtime-service.md:289`). `reassign` and `escalate`: keep waiting, start a new breach timer for the escalation SLA. `reject`: mark pending actions rejected with "SLA expired" and follow `rejected` |
| Customer reply wait | Cancel both timers; on `customerReplied`, the case service returns the extended `dueAt` and the interpreter restarts the timers (`docs/specs/agent-builder.md:458`) |
| Absolute limit | `maxWaitDays` (proposed 30) ends the wait as `reject`; never as approval |

Auto-approval on timeout is never a branch the interpreter has; the compiler refuses an `onTimeout`
other than `reassign`, `escalate` or `reject` (`docs/specs/agent-builder.md:460`).

### 4.5 Route remaining steps to people (R9)

R9 (`docs/specs/runtime-service.md:118`) selects open runs of `(workflowId, versionNumber)` from the
`run` table and sends each an Update `routeToPeople{reason}`. This adds a name to R7's list, sent by the
Runtime itself (contract change). The handler sets a flag; at the next node boundary the interpreter:

1. Lets an in-flight write activity finish, because cancelling it cannot be made safe.
2. Cancels in-flight read and agent activities.
3. Marks every remaining node `skipped` in the journal.
4. Runs the manual-handling human step with the reason, and waits for `manualComplete`.

### 4.6 Four-eyes and self-approval

The case service holds every primary check, so tokens are signed in one place
(`docs/specs/runtime-service.md:130`); the interpreter is a second line only.

| Check | Where enforced |
|---|---|
| Two distinct approvers, none of them a payload editor (`docs/specs/agent-builder.md:424`) | Case service at decision time; the API returns 409 |
| `money` actions always four-eyes (`docs/specs/agent-builder.md:427`) | Compiler refuses the plan; case service refuses a token with one approver |
| Approver may decide the action at all (`docs/specs/agent-builder.md:447`) | Case service (group membership) and data gateway (entitlement at call time) |
| No self-approval of a user-started run's action | Case service; the interpreter's validator repeats the `subject` check as a second line (4.1) |

## 5 Versioning and rollout

| Layer | Mechanism | Effect on a running run |
|---|---|---|
| Definition version | Release pointer; R1 resolves it once and records `(versionNumber, definitionDigest, planDigest)` in the start record (`docs/specs/runtime-service.md:167`) | None. The run executes its plan digest to the end (`docs/specs/agent-builder.md:354`) |
| Interpreter code | Worker Versioning, runs Pinned to their Worker Deployment Version, new builds ramp by percentage (`docs/architecture/decisions/deployment-tenancy-and-promotion.md:42`) | None. Old runs finish on the old build |
| Long runs | Continue-as-new after a human decision onto the current build, guarded by `workflow.patched()` (`docs/architecture/decisions/deployment-tenancy-and-promotion.md:51`) | The run carries the same plan digest across the continue |

The task offered a choice between Worker Versioning and plan-by-digest. They version different
things and both are needed: plan-by-digest freezes what the business approved, and Worker Versioning
freezes the code that walks it. Patching is not the general mechanism, because every patch is a branch
that later builds must keep until no history needs it. It is used in two places: the continue-as-new
upgrade, where the new build checks `workflow.patched("upgrade-<n>")` before reading carried state, and
an emergency fix to a build that still has pinned runs, with Risk sign-off and the patch id recorded on
the build until it drains.

Rollback:

| What is bad | Action |
|---|---|
| A definition version | Move the pointer back; new runs take the old version. Open runs on the bad version keep going unless R9 routes them to people (`docs/architecture/overview.md:332`) |
| An interpreter build | Set the current Worker Deployment Version back; ramped runs pinned to the bad build stay on it, so R9 is the tool for them too (`docs/architecture/overview.md:334`) |

Ramped rollout of a definition version is later: the pointer holds primary and candidate with a
percentage, chosen by a stable hash of the case key so retries land on the same version
(`docs/architecture/decisions/deployment-tenancy-and-promotion.md:46`). The interpreter needs
no change for it, because R1 has already chosen the digest.

## 6 Task queues and isolation

| Concern | Rule |
|---|---|
| Environments | Separate clusters for production and non-production; `dev` and `test` are namespaces (`docs/architecture/decisions/deployment-tenancy-and-promotion.md:26`). Queue names repeat per namespace |
| Queues per tier | `interp-<tier>`, `act-<tier>`, `agent-<tier>`, `chat-<tier>` (`docs/specs/runtime-service.md:76`–`:79`). The plan's `effectiveTier` decides every queue a run uses |
| Worker pools | One per tier, own namespace and workload identity; phase 1 runs `low` and `medium` only (`docs/specs/runtime-service.md:82`) |
| Poll authorisation | The Temporal authoriser checks the worker's identity claim per queue, so a `low` worker cannot poll `medium` (`docs/specs/runtime-service.md:461`) |
| Egress | Default-deny; workers reach Temporal, both gateways and the object store only (`docs/architecture/decisions/deployment-tenancy-and-promotion.md:28`) |
| Per-worker concurrency | Activity slots per worker sized per queue; agent turns have their own queue so slow model calls do not starve case activities (`docs/specs/runtime-service.md:82`) |
| Per-workflow concurrency | Phase 1: a cap on open non-waiting runs per workflow in the run index, checked at R1, returning 429 to the trigger, which keeps its input (proposed, open question 4) |
| Rate limits toward gateways | Enforced in the gateways per workflow identity. A `rate_limited` response is retryable with the gateway's retry-after, so interpreter-side limits are not needed (proposed) |

## 7 Failure handling

### 7.1 Retry policy by side-effect class

All values are proposed defaults; the compiler writes them into the plan.

| Class | Initial interval | Backoff | Max interval | Max attempts | Non-retryable errors |
|---|---|---|---|---|---|
| `none` (workflow code) | – | – | – | – | Every error: a CEL error is a plan defect |
| `read` (tool, knowledge, case reads) | 1 s | 2.0 | 60 s | 6 | `deny`, `not_found`, `input_invalid`, `scope_expired` |
| agent turn (resumes from the step ledger, 3.2) | 2 s | 2.0 | 60 s | 4; `internal` once | `model_denied`, `reconciliation`, `context_overflow`, `unknown_variable`, `filter_unresolved` (`docs/specs/agent-kernel.md:282`) |
| `write` with idempotent module | 2 s | 2.0 | 120 s | 6 | as `read`, plus `approval_expired`, `approval_mismatch` |
| `write` without idempotency | – | – | – | 1 | every error; then a reconciliation read decides `executed` or `failed` |
| `money` | as `write` | | | | Phase 1 has none (`docs/specs/agent-builder.md:281`) |
| case service calls | 1 s | 2.0 | 60 s | 10, then the hourly `case_unavailable` wait | `conflict` |

### 7.2 Compensation

The platform cannot reverse a write in a bank system. What is reversible:

| Effect | Reversal |
|---|---|
| Drafted actions, decision tasks | Withdrawn by the case service when the run is cancelled |
| A case opened by the run | Closed with reason "run cancelled" when no action is executed |
| A child run started | Left running; it has its own owner and gates |
| An executed write | No automatic reversal. The manual-handling step can draft a reversing action, which goes through approval like any write |

### 7.3 Poison runs and dead-letter

| Failure | Detection | Handling |
|---|---|---|
| Activity fails past its budget | Activity error | Node's `onError` → manual-handling human step; SLA keeps running (`docs/architecture/overview.md:287`) |
| Workflow task fails (interpreter bug, non-determinism) | Temporal retries the workflow task; metric `workflow_task_failed` | Alert after 3 failures (proposed); fix by a new build plus R9 or a reset to the last completed step. These runs show "Stuck: platform error" in the console |
| `maxSteps` exceeded | Interpreter counter | Non-retryable; manual handling |
| Module version revoked | Gateway denies | Manual handling (`docs/architecture/decisions/deployment-tenancy-and-promotion.md:69`) |

The dead-letter is the manual-handling queue (`docs/specs/agent-builder.md:160`): every run that
cannot continue lands with a person and a reason. No run ends silently.

### 7.4 What the console shows

A retrying step shows `waiting` with "Attempt 3 of 6: <error>". A step past its budget shows `failed`
with a detail like the mock's "Upstream returned 504 after 3 retries"
(`apps/console/src/lib/api/mock/history.ts:96`), and the run stays `waiting_review` while manual
handling is open. A run that ends without human completion is `failed` with its `error`
(`apps/console/src/components/workflows/run-trace.tsx:51`); a cancelled run is `cancelled` (spec 14
contract change 4).

## 8 Observability

### 8.1 Traces

| Span | Parent | Attributes |
|---|---|---|
| `run` | None; W3C trace id set at R1 | `runId`, `workflowId`, `version`, `planDigest`, `tier`, `environment` |
| `step.<kind>` | `run` | `stepId`, `nodeId`, `iteration`, `sideEffect` |
| `activity.<name>` attempt | `step` | `attempt`, `idempotencyKey`, result status |
| Kernel turn (spec 15 §8) | `activity.agent_turn` | turn id; model call spans below it |
| Gateway call | Propagated `traceparent` | `gatewayCallId` or `modelCallId`, joinable by `traceId` and `runId` (`docs/specs/runtime-service.md:313`) |

### 8.2 Journal rows

One `run_step` row per node execution (`docs/specs/runtime-service.md:439`), and the run sheet's
`RunStep` fields (`apps/console/src/lib/types/domain.ts:350`) come from these rows. Activities write
their own row with the side effect record. Nodes without activities (`condition`, `switch`, `gate`,
`set`, timers) are recorded by a `journal_append` local activity at the next await point.

### 8.3 Metrics

| Metric | Labels | Use |
|---|---|---|
| `opsai_steps_total` | `kind`, `status`, `tier` | Steps per second, failure rate per kind |
| `opsai_step_duration_seconds` | `kind`, `tier` | Latency per kind |
| `opsai_runs_waiting` | `on` (`person`, `customer`, `timer`, `case_unavailable`) | Open waits |
| `opsai_human_wait_seconds` | `policy`, `tier` | Time to decision |
| `opsai_sla_events_total` | `event` (`warn`, `breach`), `queue` | SLA breaches |
| `opsai_manual_handling_total` | `reason` | Dead-letter volume |
| Temporal SDK metrics | queue, build | Schedule-to-start latency, workflow task failures, pollers per build (`docs/specs/runtime-service.md:466`) |

## 9 Replay and testing

| Layer | What it does |
|---|---|
| Replay | Each interpreter build replays the corpus of recorded histories from `test` and sampled `production` before it may poll production queues (`docs/specs/runtime-service.md:457`) |
| Plan fixtures | One small plan per node kind and one per phase-1 template, checked in, with recorded activity results so tests run with no gateways |
| Eval hook | Eval runs are R1 with `mode: test` against a candidate `planDigest`; the human step records who would approve and continues as approved, and trace graders read the journal (`docs/specs/evals-and-release.md:341`, `:351`, `:363`). The interpreter's only test-specific branch is that human-step behaviour |

One test per failure mode:

| # | Failure mode | Test |
|---|---|---|
| 1 | A build changes the command sequence for an existing history | Replay of the corpus fails on the changed build |
| 2 | Worker crash mid-write double-posts | Kill the activity after the gateway accepts; retry carries the same `runId:actionId` and the stub gateway records one call |
| 3 | Duplicate trigger starts two runs | R1 twice with the same key returns the first run |
| 4 | Stale decision executes a superseded payload | Edit after approval; old token's Update is rejected by the validator |
| 5 | Expired token | Gateway stub returns `approval_expired`; action goes to `drafted` and the step re-opens |
| 6 | Self-approval reaches the interpreter | Token whose approver equals the subject is rejected by the validator |
| 7 | SLA timeout approves | Breach with `onTimeout: reject` rejects; a plan with any other timeout outcome fails to compile |
| 8 | Customer reply does not pause the SLA | Timers cancelled and restarted with the extended due time |
| 9 | Retry budget exhausted ends silently | Run lands in manual handling with the error |
| 10 | Unsupported plan schema | `plan_unsupported` before any step |
| 11 | Plan digest mismatch | `load_plan` refuses a plan whose bytes do not hash to the digest |
| 12 | Kernel interrupt lost across a wait | `Interrupt` → human step → second turn receives `Resume` with the matching `interrupt_id` and ledger |
| 12a | Agent activity retried after a crash repeats model or tool calls | Kill after two committed steps; the retry replays them from the heartbeat ledger and the fakes record no second call |
| 13 | R9 cancels an in-flight write | Write completes, remaining nodes `skipped` |
| 14 | Loop history exceeds the event limit | 500-item loop runs bodies as child workflows |
| 15 | Child run blocks the parent | Parent reaches `end` while the child waits on a person |

Each test is first seen to fail with the behaviour under test removed.

## 10 Walking skeleton

The smallest plan that runs the email reference flow (`docs/architecture/overview.md:228`) end to end:

```json
{"planSchemaVersion": 1, "workflowId": "wf_email_skeleton", "versionNumber": 1, "effectiveTier": "medium", "entry": "t1",
 "nodes": [
  {"id": "t1", "kind": "trigger", "settings": {"source": "email"}},
  {"id": "a1", "kind": "agent", "onError": "m1", "settings": {"mode": "draft", "agent": {"agentId": "drafter", "version": 1}, "actions": [{"actionId": "reply", "tool": "send_reply"}]}},
  {"id": "c1", "kind": "case", "onError": "m1", "settings": {"route": {"queueId": "q_test", "slaHours": 4}}},
  {"id": "h1", "kind": "human_step", "settings": {"mode": "approve_actions", "policyId": "p1", "actions": ["reply"]}},
  {"id": "s1", "kind": "send_reply", "onError": "m1", "settings": {"module": {"name": "m365-mail", "version": "1.0.0"}, "operation": "mail.send_reply", "actionId": "reply"}},
  {"id": "m1", "kind": "human_step", "settings": {"mode": "manual"}},
  {"id": "e1", "kind": "end", "settings": {"outcome": "done"}}],
 "edges": [["t1","next","a1"], ["a1","next","c1"], ["c1","next","h1"], ["h1","approved","s1"], ["h1","rejected","e1"], ["s1","next","e1"], ["m1","approved","e1"]]}
```

Activity options are omitted and edges are `[from, port, to]`. The full template classifies before
opening the case (`docs/specs/agent-builder.md:291`); the skeleton drafts first to stay short.

| Must exist | Owner | Skeleton level (`docs/architecture/README.md`, what is proven) |
|---|---|---|
| Plan schema v1, compiler for these five kinds, plan store by digest | Control plane | Yes |
| `InterpreterWorkflow` with `load_plan`, trigger, agent, case, human step, send reply, end, `onError` | Runtime | One worker pool |
| `agent_turn` on the agent-block host with one kernel turn (spec 15 §4) | Runtime | One alias through the AI gateway |
| `open_case`, `attach_actions`, `create_decision_tasks`, approval token signing, R7 outbox | Case service | Case, queue and SLA timer |
| `gateway_call` with the token; data gateway hash check; stubbed send | Data gateway | One allow and one deny rule |
| Mailbox intake calling R1 with the message id | Mailbox intake | One test mailbox |
| `run_step` journal and R3 for the run sheet | Runtime | Yes |
| Replay test over the skeleton's own recorded history | Runtime | Yes |

Phase 1 versus later:

| Phase 1 | Later |
|---|---|
| Kinds: trigger (email), agent (`classify`, `extract`, `draft`, `turn`), tool (read), knowledge, condition, switch on intent, case, human step (`approve_actions`, `manual`), gate with policy approval if Security accepts it, send reply, wait for customer reply, end and on error (`docs/architecture/decisions/durable-execution-runtime.md:144`) | Loop and map, delay, child workflow node, `set`, `code`, chat `reply`, `schedule`, `event`, `batch` and `api` triggers |
| Update validators, SLA timers, R7 names `actionDecided`, `customerReplied`, `manualComplete` | `routeToPeople` (R9), `reviewDecided` for gate approvals |
| Pinned Worker Versioning, replay gate on every build | Continue-as-new upgrade path, staged definition rollout |
| `low` and `medium` queues | `high` and `critical` queues, `money` writes |
| Journal, traces, the metrics in 8.3 | Per-workflow concurrency caps beyond R1 |

## 11 Open questions for the owner

1. Should the `Run workflow` node default to start-and-continue, which changes the mock's "Calls another workflow and waits" label? Recommended default: yes, with a `wait` setting for the later case where a parent needs the child's result.
2. Should a gate be its own node kind, or only a property of human steps? Recommended default: its own kind in the plan and no palette entry; the canvas keeps drawing gates on review nodes.
3. Should the interpreter's Update validator repeat the self-approval and approver-count checks that the case service already makes? Recommended default: yes, as a second line that costs no I/O.
4. Do we need a per-workflow cap on concurrent runs in phase 1? Recommended default: a cap on open non-waiting runs per workflow checked at R1, default 200, with gateway rate limits handling the rest.
5. At what item count does a loop switch to child workflows? Recommended default: 50 items.
6. What is the absolute wait limit for a human step before it rejects? Recommended default: 30 days, aligned with the continue-as-new threshold (overview open question 7).
7. Are the retry defaults in 7.1 acceptable to the module owners of the first workflow? Recommended default: yes, with per-module overrides only toward fewer attempts.
8. Should `RunStep.kind` gain `logic` and `wait` in addition to spec 14's three new kinds? Recommended default: yes, so condition, gate and timer steps show in the run sheet with a distinct icon.

## 12 Sources

Files opened for this spec, relative to the ops-ai repository root: `docs/specs/runtime-service.md`
(whole file); `docs/architecture/decisions/durable-execution-runtime.md`, `workflow-definition-format.md`
and `deployment-tenancy-and-promotion.md`; `docs/architecture/overview.md` (layering, throughput,
end-to-end, failure modes, open questions); `docs/architecture/service-map.md`; `docs/architecture/README.md`;
`docs/specs/agent-builder.md` (4.1–4.8, 5.2–5.8); `docs/specs/data-and-ai-gateways.md` (4.1a);
`docs/specs/evals-and-release.md` (5.2); `docs/specs/agent-kernel.md` (2.1, 2.2, 4.5, 4.7, 5); `apps/console/src/components/workflows/node-types.ts`,
`run-sheet.tsx`, `run-trace.tsx`; `apps/console/src/lib/types/domain.ts` (Workflow, WorkflowGraph,
GatePolicy, RunStep, WorkflowRun, AgentTestTurn); `apps/console/src/lib/api/mock/history.ts`; and by
grep only `graph-checks.ts`, `node-palette.tsx` and `apps/console/src/app/workflows/[id]/page.tsx`.

Not opened: ADR-0002, ADR-0005, ADR-0006 (cited through
spec 14 and the overview), and Temporal's Python SDK and limits documentation; the SDK function names
and payload limits above are **unverified**.
