# 15 Agent kernel

Status: draft for review. Binding inputs: ADR-0001 (Temporal interpreter), ADR-0002 (Python Runtime),
ADR-0003 (workflow definition), ADR-0005 (identity and entitlement), ADR-0008 (AI gateway) and
ADR-0009 (chat) and ADR-0014 (agent loop library), all in `docs/architecture/decisions/`; specs `01`,
`02`, `03`, `04`, `07`, `11`, `12`, `13` and `14`; `docs/specs/design-lessons.md`. The kernel contract
refers to "the loop library chosen in ADR-0014" and holds for LangGraph Python, OpenAI Agents SDK,
Pydantic AI or a loop of our own. ADR-0014 picks Pydantic AI for phase 1; section 4.6 records how the
kernel uses it. Grounded in the console
mock's `apps/console/src/lib/types/domain.ts`, `lib/types/chat.ts`, `lib/api/chat-contract.ts`,
`lib/api/mock/agent-wrappers/index.ts` and `components/chat/widgets.tsx`. File references are
`path:line` for files opened for this spec; anything else is marked unverified.

## Summary

The kernel is one Python package, `ops_agent_kernel`, that runs one turn of one agent version. Two
callers use it: the interpreter's agent activity on the agent-block host (a workflow node, `01` node 7,
`docs/specs/agent-builder.md:387`) and the chat turn activity on the chat turn worker
(`docs/specs/runtime-service.md:78-79`). A turn takes a `TurnRequest` that names everything it may
read and call, and returns a `TurnResult` plus a stream of events. The kernel assembles context, calls
the model through the AI gateway, calls tools through the data gateway, stops, and reports. When a tool
needs a person or the agent needs an answer, the turn ends with an `Interrupt`; the caller persists it,
waits, and starts a new turn with a `Resume`. The kernel stores nothing. Run state, transcripts, drafted
actions and memory pages are written by the Runtime and the services around it.

## 1 What the kernel is and is not

**What it is.** A library imported by two Temporal activities. Given a pinned agent version that the
Runtime has already resolved, the run context token minted for this activity (`03` 4.3,
`docs/specs/data-and-ai-gateways.md:242-252`), the transcript so far, the inputs, a budget, the
allowed tools, knowledge bases and skills, it runs the model and tool loop for one turn. It composes the
prompt in the cache-friendly order (section 3), streams events to a sink the caller provides (section
6), keys every tool call so a retried activity cannot repeat a side effect (section 4.5), and returns
usage, citations and the tool call records with gateway call ids. Packaged agents (`AgentPackage`,
`docs/specs/agent-builder.md:171`) run their own code, and the kernel hands that code the same model
client, tool client and sink, so gateway, streaming and idempotency rules hold for them too.

**What it is not.** It has no persistence: no database, no checkpointer, no cache that outlives the
process, and no write to the run journal, the transcript or the Wiki. It holds no keys: model keys live
in the key-and-budget service (`docs/specs/data-and-ai-gateways.md:469`) and system credentials in
the data gateway (`docs/specs/runtime-service.md:90-91`). It makes no policy decision: whether a
call is allowed, which subject it binds to, whether a write needs approval and who may approve are
decided by OPA in the data gateway and by the case and review services
(`docs/specs/runtime-service.md:195-198`). It reads no definitions: it never calls the registry, and
it runs only the agent version the caller passes in, already pinned by the run
(`docs/specs/runtime-service.md:95`). It does not choose which turn to run or when; the interpreter
and the chat session workflow own that.

| Concern | Owner | Kernel's part |
|---|---|---|
| Which agent version runs | Registry and the run's pins (`14` 5.1) | Receives it resolved |
| Allow or deny a tool call, subject binding, approval-token check | Data gateway with OPA (`03` 5.3) | Sends the call, reports the result |
| Model key, alias resolution, budget ledger | Key-and-budget service (ADR-0008, `03` 5.8) | Names the alias, reads the usage returned |
| Drafted actions, reviews, approval tokens | Case and review services (`14` 5.6) | Returns an `Interrupt`; forwards a token on `Resume` |
| Transcript, chat messages, run journal | Runtime and the control plane chat module (`14` 7) | Returns parts and records; emits events |
| Remembered Wiki pages | Runtime, through the knowledge module | Returns `MemoryProposal`s (section 7) |

## 2 Inputs and outputs of a turn

### 2.1 `TurnRequest`

| Field | Type | Source and rule |
|---|---|---|
| `turn_id` | `str` | Runtime; equals the chat `turnId` (`14` R11) or `stepId:attempt-free` for a node |
| `agent` | `AgentVersionRef{agent_id, version, digest}` | The pinned version (`docs/specs/agent-builder.md:170`) |
| `settings` | `AgentSettings` | Resolved from the version: `instructions: list[PromptFragment{text, stable: bool}]`, `model_alias`, `guardrails{redact_pii, max_tool_calls_per_turn, when_unsure, blocked_topics}` (mock `AgentGuardrails`, `apps/console/src/lib/types/domain.ts:49-54`), `allow_ungrounded`, `temperature?`, `max_output_tokens?` |
| `variables` | `dict[str, str]` | Display values for `{key}` placeholders, filled by the Runtime from the case and session (`docs/specs/prompts.md:98-100`, `:180`). Unknown keys fail the turn with `unknown_variable` |
| `run_context` | `RunContext{token, run_id, step_id, workflow_id, workflow_version, environment, mode}` | `token` is the signed run context (`03` 4.3) with `sub`, `act`, `bindings`, `riskTier`; the kernel forwards it opaque to both gateways and reads only the unsigned ids for traces |
| `transcript` | `TranscriptRef{file_id \| message_ids[], up_to}` | By reference (`07` CD-2); read through the `files` port. Empty for a workflow node |
| `input` | `UserTurn{content, attachments[file_id]}` or `NodeInput{fields: dict, instruction?}` | Chat message, or the node's mapped inputs |
| `budget` | `TurnBudget{max_steps, max_tool_calls, max_cost_usd, deadline, context_tokens}` | `max_tool_calls` from guardrails; `deadline` 120 s for chat (`docs/specs/runtime-service.md:463`); `context_tokens` from the alias capabilities (`docs/specs/data-and-ai-gateways.md:347`) |
| `tools` | `list[ToolGrant]` | `{name, module, module_version, operation, access (read \| write \| money_movement), input_schema, workflow?{workflow_id, tier, approval}}` from the version's grants and module manifests (`effectiveTools`, `01` 4.5). Platform tools (`load_skill`, `search_knowledge`, `remember`) are added by the kernel when the version enables them |
| `knowledge` | `list[KbRef{kb_id, config_version}]` | Already intersected: pinned modules ∩ the thread's narrowing (`07` CD-8, `docs/specs/agent-chat.md:30`) |
| `skills` | `list[SkillPin{skill_id, version, loading, use_when, body_ref, guardrails, tokens}]` | Pins on the version (`docs/specs/skills.md:82-83`) |
| `memory` | `MemoryScope \| None` | `{collection, subject_binding, recall_k, propose: bool}`; `subject_binding` names a run-context binding such as `case.customerId`, never a value |
| `sink` | `StreamSink` | Where events go (section 6) |
| `trace` | `TraceContext{traceparent, tracestate}` | The run's W3C trace (`docs/specs/runtime-service.md:313-315`) |
| `resume` | `Resume \| None` | Present when this turn continues an interrupted one (section 5) |
| `ledger` | `StepLedger \| None` | Steps completed by an earlier attempt of the same activity (section 4.5) |
| `ports` | `KernelPorts{ai, data, files, clock, ids}` | Clients the caller constructs; tests swap them for fakes (section 9) |

### 2.2 `TurnResult`

| Field | Type | Meaning |
|---|---|---|
| `turn_id` | `str` | Echo |
| `status` | `completed \| interrupted \| stopped \| failed` | `stopped` is a user cancel (`docs/specs/agent-chat.md:133-148`) |
| `stop_reason` | `final \| max_steps \| max_tool_calls \| budget \| deadline \| interrupt \| cancelled \| error` | Section 4.4 |
| `parts` | `list[MessagePart]` | Final assistant message: text (with `[n]` markers), tool parts, widget refs, source refs; partial text is kept on `stopped` and `failed` |
| `tool_calls` | `list[ToolCallRecord]` | `{tool_call_id, key, module, module_version, tool, access, input_hash, input_ref, output_ref, status (ok \| error \| denied \| gated), deny_reason?, gateway_call_id, duration_ms, child_run_id?}`; matches `ToolCallRecord` in `docs/specs/agent-chat.md:105` |
| `citations` | `list[Citation]` | `{n, documentId, title, section, page?, version, snippet, url?, precedenceNote?, stale}` (`07` entities, `docs/specs/knowledge.md:293`) |
| `no_answer` | `bool` | Retrieval found nothing above threshold (`docs/specs/agent-chat.md:220-222`) |
| `loaded_skills` | `list[LoadedSkill]` | `{skillId, name, version, matched}`, the mock's shape (`apps/console/src/lib/types/skills.ts:436-442`) |
| `usage` | `Usage{input_tokens, output_tokens, cached_tokens, cost_usd, model_call_ids[]}` | Summed from AI gateway responses; the gateway's log is the record (`03` 4.8) |
| `interrupt` | `Interrupt \| None` | Section 5 |
| `memory_proposals` | `list[MemoryProposal]` | Section 7 |
| `truncation` | `{transcript_messages_dropped, passages_dropped, tool_output_truncated[]}` | Recorded on the turn (`docs/specs/agent-chat.md:201-202`) |
| `context_digest` | `dict[section, sha256]` | Hash of each assembled context section, for evidence (section 8) |
| `ledger` | `StepLedger` | Final state; the caller may discard it after the result is stored |
| `error` | `KernelError{class, code, message, retryable} \| None` | Section 4.7 |

`TurnResult` serves `AgentTestTurn` (`apps/console/src/lib/types/domain.ts:375-388`) without a join:
`reply` from text parts, `toolCalls`, `citations`, `wouldPause` from an approval interrupt in `test`
mode, `skills` from `loaded_skills` and `startedRuns` from `child_run_id`s.

## 3 Context assembly

### 3.1 Order

Sections are assembled stable first, so the AI gateway's prefix cache covers as much input as possible
(`docs/specs/design-lessons.md:112`, `docs/specs/agent-chat.md:199-200`).

| # | Section | Position in the request | Cache class | Rule |
|---|---|---|---|---|
| 1 | Agent instructions, stable fragments | System message, first | Stable per version | Fragments in version order (`docs/specs/agent-builder.md:170`) |
| 2 | Always-on skill bodies | System message, after 1 | Stable per version | Pin order; each recorded as loaded with "Always on" (`docs/specs/skills.md:180`) |
| 3 | Skill index | System message, after 2 | Stable per version | Name and use-when of each `on_match` pin (`11` 5.3.1) |
| 4 | Tool definitions | Request `tools` | Stable per version | Grants plus platform tools; sorted by name so the order is deterministic |
| 5 | Instruction fragments with variables | System message, last | Volatile | `{key}` filled from `variables`; display values only |
| 6 | Transcript window | Messages | Grows per turn | Non-superseded messages, oldest dropped first (`07` rule 16) |
| 7 | Memory recall | Data block on the user turn | Volatile | Section 7 |
| 8 | Knowledge passages with citation numbers | Data block on the user turn | Volatile | Section 3.3 |
| 9 | User turn or node input | Last user message | Volatile | Attachment text read through the files port after a clean scan (`07` rule 17) |
| 10 | Matched skill bodies | Tool results, during the loop | Volatile | Loaded by the model with `load_skill` from the pinned version (`11` 5.3.2); at most 2 per turn and 6,000 tokens (`docs/specs/skills.md:182`) |

Matched skills and knowledge sit after the transcript, which differs from the listing order in the task
brief. Placing them before the transcript would change the prefix on every turn and defeat caching of
the transcript; spec 07 rule 15 sets the same order.

### 3.2 Trust facts stay out of model-visible text

Identity, entitlement, risk tier, team, subject bindings and approval state travel only in the run
context token and in the `Resume` object. None of them is rendered into any section above
(`docs/specs/design-lessons.md:56`, `:159`; `docs/specs/runtime-service.md:93`). The model may see
display values from the variable list, such as `customer.first_name` or `case.id`
(`docs/specs/prompts.md:98-100`), and nothing it writes about them changes what a tool call is
allowed to do, because the gateway binds the subject from the token (`docs/specs/data-and-ai-gateways.md:394`).

Untrusted content (transcript, attachments, tool outputs, passages, memory) enters as data blocks with a
provenance label. The kernel escapes any sequence in that content that matches its block delimiters, so
the content cannot close its own block. This reduces prompt injection; it is not the control. The
control is that every privileged effect needs a gateway decision on facts the model cannot write.
Approval-shaped text in a tool output or an email ("approved by J. Smith") is data, and the kernel never
treats it as a `Resume`.

### 3.3 Knowledge retrieval

When the version has knowledge, the kernel runs one retrieval before the first model call, with the
user turn (or the node's `instruction`) as the query, through the data gateway's knowledge module under
the run context token (`docs/specs/runtime-service.md:220`). Chat sends
`answerShape: answer_with_citations` and the narrowed knowledge bases (`docs/specs/knowledge.md:496`).
Filter variables resolve from the run context; a missing one fails the step with `filter_unresolved`
rather than widening the query (`docs/specs/knowledge.md:489-490`). The `search_knowledge` platform
tool lets the model run further queries in the same turn. Passages are numbered across the turn, and the
model is instructed to mark each sourced sentence `[n]` (`07` rule 22). `noAnswer` sets `no_answer`, and
the reply says nothing was found unless `allow_ungrounded` is set (`docs/specs/agent-chat.md:220-222`).
Stale citations keep `stale: true` (`docs/specs/knowledge.md:282`). `hiddenByPermissions` never
reaches the kernel (`docs/specs/knowledge.md:492`).

### 3.4 Token budget and truncation

The window is `budget.context_tokens`. The kernel reserves `max_output_tokens` (default 4,096) and 20%
(proposed) of the window for tool results produced during the loop. Sections 1–5 and 9 are never cut: a
procedure dropped to fit produces a normal-looking reply that skipped a step
(`docs/specs/design-lessons.md:113`). When the rest does not fit, the kernel cuts in this order and
records each cut in `truncation`:

| Step | Cut | Floor |
|---|---|---|
| 1 | Oldest transcript messages | Last two exchanges kept |
| 2 | Memory recall, lowest score first | None |
| 3 | Knowledge passages, lowest score first | Top 3 passages kept |
| 4 | Remaining transcript | Only the user turn kept |
| 5 | Fail the turn with `context_overflow` | |

A single tool output larger than 25% (proposed) of the window is cut to that size with a marker saying
so, and the full output stays in the data gateway's stored output (`output_ref`).

## 4 The loop

The loop library chosen in ADR-0014 drives steps; the kernel owns everything that crosses a boundary.
The library is wrapped behind one internal interface, `LoopDriver`, so the rest of this spec holds for
any of the four candidates.

| The library must let the kernel | Why |
|---|---|
| Inject the model client (base URL, headers) | All model traffic goes to the AI gateway with the run context token (`03` 5.8.1–5.8.2) |
| Intercept each tool call before it executes, and end the turn there | Gated writes become interrupts (section 5) |
| Observe every text, reasoning and tool event as it happens | Streaming (section 6) |
| Run without its own persistence or checkpointer | The kernel has none (section 1) |
| Run against a recorded model deterministically | Replay tests (section 9) |

ADR-0014 compares the candidates against these rows; section 4.6 covers the phase-1 pick.

### 4.1 Model calls

Each step calls `POST /v1/chat/completions` at the key-and-budget service with `model` = the version's
alias, the run context token, the trace headers and `x-opsai-sensitivity` set to the highest sensitivity
among passages and tool outputs in the request (`docs/specs/runtime-service.md:237`,
`docs/specs/data-and-ai-gateways.md:473`). The service resolves `alias@version`, attaches the
workflow's key and checks the per-run and monthly budget (`docs/specs/data-and-ai-gateways.md:467-470`).
The kernel records the returned `modelCallId`, tokens and cost. Before each step the kernel also checks
its own ceiling, `budget.max_cost_usd`, against the running cost, so a turn stops before it starts a
step it cannot pay for; the gateway's ledger remains the authority.

### 4.2 Tool calls

Each tool call goes to the data gateway (`tools/call` over MCP, `docs/specs/runtime-service.md:192`)
with the run context token. The gateway authenticates, resolves the pinned module version, asks OPA,
binds the subject, checks the approval token for writes, attaches the idempotency key and logs the call
(`docs/specs/data-and-ai-gateways.md:391-399`). The kernel validates the model's arguments against
`input_schema` first and returns a validation error to the model without calling the gateway.

| Gateway answer | Kernel action |
|---|---|
| `ok` | Output to the model as a data block; `tool-output-available` |
| `error` from the system | Error to the model, which may retry with other arguments or explain; the turn continues |
| `deny` with a reason (`docs/specs/data-and-ai-gateways.md:303`) | `tool-output-denied`; the model is told the call was not permitted, with not-found and not-permitted worded the same (`03` 3.10); never retried |
| `gated` (write or money movement needing approval) | The turn ends with an `Interrupt` of kind `approval` (section 5) |
| `gateway_degraded` | Retried by the activity, never by the model (`docs/specs/runtime-service.md:209-211`) |
| Workflow tool started a child run | Output carries `childRunId`; `data-run` part; the turn does not wait for the child (`docs/specs/runtime-service.md:62-67`) |

Errors go back to the model as information instead of raising, as Protobox does today
(`protobox/services/agent-service/src/tools/services/agent-tool-runner.service.ts:187-189`).

### 4.3 Parallel tool calls

When the model returns several calls in one step, `read` calls run concurrently, at most 4 (proposed).
`write`, `money_movement` and workflow-tool calls run one at a time in the order the model gave them,
after the reads. If one of them returns `gated`, the kernel finishes the reads already started, does not
start the remaining writes, and ends the turn with the interrupt; the remaining calls are recorded as
`not_started` and the model sees them again on resume. `max_tool_calls_per_turn` counts every call
attempted, including denied ones.

### 4.4 Stop conditions

| Stop reason | When | Status | Text kept |
|---|---|---|---|
| `final` | A model step returns no tool call | `completed` | Yes |
| `max_steps` | `budget.max_steps` reached; default 8, the Protobox default (`protobox/services/agent-service/src/tools/services/agent-tool-runner.service.ts:20-21`) | `completed`, with a stated "stopped after N steps" when there is no final text (`:101-107`) | Yes |
| `max_tool_calls` | Guardrail reached | `completed`; the model gets one last step with tools disabled to answer | Yes |
| `budget` | Kernel ceiling or gateway `budget_exceeded` | `failed`, no retry (`07` rule 21) | Yes |
| `deadline` | `budget.deadline` passed | `failed` | Yes |
| `interrupt` | Approval, question or hand-off | `interrupted` | Yes |
| `cancelled` | Activity cancellation (chat stop, `docs/specs/agent-chat.md:210-212`) | `stopped`; the in-flight model request is cancelled | Yes |
| `error` | Non-retryable error (4.7) | `failed` | Yes |

### 4.5 Retries and idempotency

A Temporal activity can be retried after a crash mid-turn. A naive retry re-runs the model, which may
choose different calls, and repeats calls already made. The kernel prevents both with a step ledger and
deterministic keys.

| Mechanism | Rule |
|---|---|
| Step ledger | After each model step and each tool result, the kernel calls `sink.commit(step)` with references only (model output stored through the files port, tool output already stored by the gateway). The activity records the ledger as Temporal heartbeat details. A retried attempt passes the ledger back in `TurnRequest.ledger`, and the kernel replays committed steps from it without calling the model or the tools again |
| Tool call key | `run_id:turn_id:step:ordinal`, deterministic given the ledger |
| Action id for writes | First 16 hex characters of SHA-256 of the tool call key; the gateway's idempotency key is `runId:actionId` (`docs/specs/data-and-ai-gateways.md:306`, `:396`) |
| Workflow tools | The tool call key is the child run's `trigger.key`, so R1 returns the existing run for a repeat (`docs/specs/runtime-service.md:110`) |
| Input hash | SHA-256 of canonical JSON of the input, computed by the same function the gateway and case service use (`docs/specs/data-and-ai-gateways.md:395`); the function lives in `packages/contracts` |
| In-flight step at crash | Re-requested; the gateway logs a second attempt. A write in flight is protected by the idempotency key; a module with `idempotency: none` returns `requires_reconciliation`, which fails the turn into the human step (`03` 3.6) |

### 4.6 Implementation notes: Pydantic AI in phase 1

ADR-0014 picks Pydantic AI for the Python runtime, run as a plain agent inside the agent-block host and
chat turn activities, without its Temporal integration (`TemporalDurability`) in phase 1
(`docs/architecture/decisions/agent-loop-library.md:94-97`). The kernel contract in sections 2
to 9 does not change with the library; this table records where each kernel piece sits on it.

| Kernel piece | Phase-1 implementation |
|---|---|
| `LoopDriver` | One Pydantic AI agent run per turn; the agent object is built per turn from `AgentSettings` and holds no state between turns |
| Model client | A Pydantic AI model provider pointed at the key-and-budget service, with the run context token and trace headers (`agent-loop-library.md:99-100`) |
| Context assembly (section 3) | Our code; the library receives the assembled system prompt and messages |
| Gated writes and `Interrupt` (section 5) | Deferred tools: the run ends with `DeferredToolRequests`, the activity returns them as an `Interrupt`, and a new activity resumes with `DeferredToolResults` built from the `Resume` (`agent-loop-library.md:96-97`) |
| Approval token bound to the input hash | Our code. The kernel computes the canonical-JSON SHA-256 of the tool input, the case service signs the token over it, and the data gateway verifies it on execution (`agent-loop-library.md:100-101`). The library only ends and resumes the run |
| Streaming (section 6) | `VercelAIAdapter` with `sdk_version=6`, which emits the AI SDK UI message stream including tool-approval parts (`agent-loop-library.md:48`, `:98`). Its output is written to the `StreamSink`; the kernel's own `data-*` parts (`data-status`, `data-run`, `data-skill`, `data-interrupt`) are added by the kernel. Which part names the adapter emits for approvals, and whether they replace `data-interrupt`, is unverified until the adapter is run |
| Step ledger (section 4.5) | Our code around the run: commits after each model response and tool result. Pydantic AI's own durability is not used in phase 1 |
| Trace writer (section 8) | Our code |
| Packaged LangGraph agents | Keep running as `AgentPackage` on the same host (`agent-loop-library.md:102`) |

### 4.7 Error classes

| Class | Examples | Retry | Turn outcome |
|---|---|---|---|
| `model_denied` | `budget_exceeded`, `sensitivity_not_cleared`, `alias_not_pinned` | Never | `failed`; the caller routes to the human step (`docs/specs/runtime-service.md:249-252`) |
| `model_transient` | 429, 5xx after the gateway's 2 retries | Activity retry with the ledger | `failed` past the activity budget |
| `tool_denied` | Any `denyReason` | Never | Continues; the model is told |
| `tool_error` | Upstream error, timeout, output schema mismatch | By the model only | Continues |
| `gateway_degraded` | OPA, secret store or call log down | Activity retry | `failed` past the budget, then the human step |
| `reconciliation` | `requires_reconciliation` | Never | `failed`; a person reconciles |
| `context_overflow`, `unknown_variable`, `filter_unresolved` | Assembly errors | Never | `failed` before any model call |
| `cancelled` | Stop | No | `stopped` |
| `internal` | Kernel defect | Activity retry once | `failed` |

## 5 Interrupts

A turn ends with an `Interrupt` when it cannot continue without something from outside the kernel.

| Field | Type | Meaning |
|---|---|---|
| `interrupt_id` | `str` | Equals the tool call key for `approval`, else `turn_id:q` |
| `kind` | `approval \| question \| handoff` | `question` and `handoff` come from `whenUnsure` (`apps/console/src/lib/types/domain.ts:52`) |
| `needed` | `str` | Plain text for the person: "Approval of a transfer of 1,250.00 to account ending 4411" |
| `pending_call` | `{tool_call_id, key, action_id, module, module_version, tool, access, input_ref, input_hash}` | For `approval`: the exact payload the reviewer will see and the token will bind to |
| `question` | `str?` | For `question` |
| `ledger` | `StepLedger` | So the resumed turn continues from the same point |

The caller persists the interrupt. The interpreter attaches the action to the case and waits on R7
`actionDecided` (`docs/specs/runtime-service.md:286-290`); the chat session creates the drafted
action and review and waits on R14 `reviewDecided` (`docs/specs/runtime-service.md:123`). In chat,
the caller also writes the closing stream parts: the `data-widget` approval and `finish`. Then it starts
a new turn with a `Resume`.

| `Resume` field | Meaning |
|---|---|
| `interrupt_id` | Must match |
| `decision` | `approved \| rejected \| answered \| handed_off` |
| `approval_token` | Signed by the case service, bound to `caseId`, `actionId` and `input_hash` (ADR-0005, `docs/architecture/decisions/identity-and-entitlement.md:35`); opaque to the kernel |
| `reason` | Required on `rejected` (`07` rule 33) |
| `answer` | For `question` |

On `approved` the kernel sends the stored `input_ref` payload byte for byte with the token and the same
idempotency key, emits the result, and continues the loop. On `rejected` the model receives "The
reviewer rejected this action: <reason>" as the tool result and continues. The kernel never edits the
payload; an edited action is a new approval (`docs/specs/design-lessons.md:165`). A policy approval
token (`docs/architecture/decisions/identity-and-entitlement.md:36`) follows the same path
with a resume that arrives at once.

In chat, the person who asked cannot approve a money movement they caused (`07` CD-7,
`docs/specs/agent-chat.md:238-240`), so the approver is another eligible reviewer, and the API
requires a step-up token from the last 5 minutes (`docs/specs/sign-in-and-sessions.md:114-117`).

```mermaid
sequenceDiagram
  participant U as Requester (chat)
  participant RT as Runtime + kernel
  participant DG as Data gateway
  participant RV as Reviewer via review service
  U->>RT: R11 "pay invoice 4411"
  RT->>DG: tools/call payments.transfer (run context)
  DG-->>RT: gated; turn ends Interrupt(approval, input_hash)
  RT-->>U: data-widget approval, finish
  RV->>RV: approve; step-up token checked (13 3.7)
  RV->>RT: R14 reviewDecided + approval token
  RT->>DG: same input + token + runId:actionId
  RT-->>U: resumed turn streams result and reply
```

`question` in chat ends the turn with the question as the reply; the next user message is the answer,
so no `Resume` is needed. In a workflow node, `question` and `handoff` become a human step on the case.

## 6 Streaming

### 6.1 Kernel events and UI parts

The kernel emits typed events to `TurnRequest.sink`. Each maps to one AI SDK UI message stream part
(`07` CD-11, `docs/specs/agent-chat.md:312-323`). Parts marked "not in 07" are additions this spec
proposes; their exact AI SDK names are unverified.

| Kernel event | UI message stream part | Mock `ChatStreamEvent` (`apps/console/src/lib/types/chat.ts:200-209`) |
|---|---|---|
| `TurnStarted{message_id, metadata}` | `start` | `start` |
| `StatusChanged{phase}` | `data-status` (transient) | `status` |
| `TextStarted` / `TextDelta` / `TextEnded` | `text-start` / `text-delta` / `text-end` | `text` |
| `ReasoningDelta` | `reasoning-start` / `-delta` / `-end` (not in 07) | none |
| `ToolInputStarted`, `ToolInputAvailable` | `tool-input-start`, `tool-input-available`; name prefixed by module | `tool_start` |
| `ToolOutput` | `tool-output-available` | `tool_end` |
| `ToolError` | `tool-output-error` | `tool_end` (`status: failed`) |
| `ToolDenied` | `tool-output-denied` | none (`ToolCall.status` has no denied value) |
| `WidgetProduced{view, module, module_version, tool_call_id, as_of, payload}` | `data-widget` | `widget` |
| `ChildRunStarted{run_id, workflow_id}` | `data-run` (`docs/specs/runtime-service.md:408`) | none |
| `SkillLoaded{LoadedSkill}` | `data-skill` (transient, not in 07) | none |
| `CitationsReady[]` | one `source-document` each, before `finish` | `citations` |
| `Interrupted{Interrupt}` | `data-interrupt` (not in 07); the caller then writes `data-widget` and `finish` | none |
| `TurnFailed{class, message}` | `error`, then `finish` | `error` |
| `TurnFinished{usage, stop_reason}` | `finish` with message metadata | `done` |
| `StepCommitted` | not streamed; ledger only | none |

Widgets come from tool outputs whose `structuredContent` conforms to an `ops-views` view (`07` CD-4).
The six views match the console's renderer registry (`apps/console/src/components/chat/widgets.tsx:335-342`).
The kernel never produces an approval widget itself; approvals are host-rendered after the caller has
created the review (`07` CD-3).

### 6.2 How the Runtime relays it

On the chat turn worker, the sink is a relay writer that appends each part to a Redis stream keyed
`runId:turnId` and sets a 10-minute expiry after `finish` (`docs/specs/runtime-service.md:80`,
open question 3 at `:484`). The Runtime API's R11 and R12 read the stream and serve SSE to the BFF
(`docs/specs/runtime-service.md:120-121`). Parts never enter Temporal history
(`docs/specs/agent-chat.md:309`). The kernel knows only the `StreamSink` interface, so the store can
change without touching it.

### 6.3 A workflow node without a client

The interpreter's agent activity passes a buffering sink that keeps nothing but the ledger commits and
the final parts; no relay is written and no client reads. The agent Test sheet uses the relay sink on
the chat turn worker (`07` CD-12, `docs/specs/agent-chat.md:34`), so the same event sequence is
exercised in phase 1 before chat exists.

## 7 Memory

Memory across threads is out of scope for chat phases 2a and 2b (`docs/specs/agent-chat.md:44`), so
this section describes the later shape that the kernel's types reserve now.

| | Rule |
|---|---|
| What is written | A remembered page in the Wiki, provenance `remembered`, unverified until a person marks it (`apps/console/src/lib/types/wiki.ts:6-7`), in the memory scope's collection |
| How | The model calls the platform `remember` tool. The kernel does not call any gateway for it; it returns `MemoryProposal{title, body, collection, subject_binding, source_refs[], tool_call_id}` in `TurnResult` |
| Who writes | The Runtime, after the turn, through the knowledge module with the run context token, so the collection's permissions and the subject binding apply. A proposal whose collection is outside the scope is dropped and logged |
| What is read | Before the first model call, recall searches the scope's collection for pages bound to the same subject, `recall_k` results, as a data block marked with each page's verified state |
| Subject | Taken from the run context binding named by `subject_binding`; the model cannot name another customer (`docs/specs/design-lessons.md:45`) |

The Protobox chat injects customer memories into the system prompt as text
(`protobox/services/agent-service/src/chat/chat.service.ts:1375-1377` places the dynamic customer context
ahead of the stable prompt). The kernel places recall after the transcript instead (section 3.1).

## 8 Tracing and evidence

| Span | Parent | Attributes |
|---|---|---|
| `agent.turn` | The activity span of the step (`14` 8 observability) | `runId`, `turnId`, `stepId`, `workflowId`, `workflowVersion`, `agentId`, `agentVersion`, `agentDigest`, `stopReason`, `tokens`, `costUsd` |
| `agent.context` | `agent.turn` | Section sizes and `truncation`; no content |
| `agent.model_call` | `agent.turn` | `alias`, `modelCallId`, tokens, cached tokens, latency, attempt |
| `agent.tool_call` | `agent.turn` | `module`, `moduleVersion`, `tool`, `access`, `gatewayCallId`, `toolCallKey`, `inputHash`, `decision`, latency |
| `agent.retrieval` | `agent.turn` | `kbIds`, query record id, passages returned, `noAnswer` |

The trace context goes to both gateways on every call, so their logs join on `traceId` as well as
`runId` (`docs/specs/runtime-service.md:313-315`). Neither gateway logs prompt or completion bodies
(`docs/specs/data-and-ai-gateways.md:471`); the run journal holds them by reference.

The caller writes the step journal row with `gateway_call_ids[]` and `model_call_ids[]`
(`docs/specs/runtime-service.md:439`). For the evidence bundle sealed on a version
(`docs/specs/evals-and-release.md:35`), each eval case's journal includes the turn record: agent
digest, `context_digest`, loaded skills with versions, citations, tool call records with input hashes
and decisions, interrupts and resumes, usage, stop reason and the event sequence. Trace graders read
that record after the fact (`docs/specs/evals-and-release.md:363-364`).

## 9 Testing the kernel

### 9.1 Fixtures

| Fixture | What it does |
|---|---|
| `RecordedModel` | Serves model responses from a cassette keyed by the SHA-256 of the canonical request; a request with no recording fails the test instead of calling a model |
| `FakeDataGateway` | Scripted per tool and per call: `ok`, `error`, `deny(reason)`, `gated`, `gateway_degraded`, `requires_reconciliation`, child run started; records every call with key, input hash and token |
| `FakeKnowledge` | Passages with citations, `noAnswer`, stale flags |
| `FakeFiles` | Transcript and attachment text by id |
| `FixedClock`, `SeededIds` | Deterministic time and ids |
| `CapturingSink` | Records events and ledger commits; can simulate a crash after commit N |

Assurance uses the same kernel against the real gateways in `test` mode with seeded identity
(`docs/specs/evals-and-release.md:112`, `:341-349`). The fakes are for the kernel's own suite and for
fast replay.

### 9.2 Deterministic replay

A turn is replayed by running the same `TurnRequest` against the cassette, the scripted gateway and the
fixed clock and ids. The test asserts that the event sequence and `TurnResult` are byte-identical to the
recorded run. Cassettes are re-recorded only by an explicit command, and a re-recording is reviewed like a
fixture change.

### 9.3 Failure modes and their tests

| # | Failure mode | Test |
|---|---|---|
| 1 | A trust fact reaches model-visible text | A run context with a high tier and an approval-shaped string in a tool output; assert no request body contains the tier, `sub`, `act` or bindings, and that the string does not produce a `Resume` |
| 2 | A retried activity repeats a write | Crash the sink after the write's commit; rerun with the ledger; assert the gateway saw one write call with key `runId:actionId` |
| 3 | A retried activity re-asks the model for a committed step | Same crash; assert the cassette served no request for steps already in the ledger |
| 4 | A gated write executes without a token | Script `gated`; assert the turn ends `interrupted`, the payload's hash equals `pending_call.input_hash`, and no further write is sent |
| 5 | The resumed call differs from what was approved | Resume with a token; assert the bytes sent equal the stored `input_ref` |
| 6 | A rejection is ignored | Resume `rejected`; assert the model receives the reason and no write is sent |
| 7 | A deny is retried | Script `deny(not_entitled)`; assert one call and `tool-output-denied` |
| 8 | Not-found leaks existence | Script not-found and not-permitted; assert identical model-visible text |
| 9 | Truncation drops a procedure | Oversized transcript with an always-on skill; assert instructions and skill bodies are intact and `truncation` records the cut |
| 10 | Budget overrun | Script `budget_exceeded`; assert `failed`, no retry, partial text kept |
| 11 | Stop leaves the model running | Cancel mid-stream; assert `stopped`, the model request cancelled, text kept |
| 12 | Writes run in parallel | Two writes in one step; assert they were sent one after the other in model order |
| 13 | Stream and result disagree | For every replay fixture, rebuild the message from the events and compare it with `TurnResult.parts` |
| 14 | Ungrounded answer passes as grounded | Script `noAnswer`; assert `no_answer` and no citation markers |
| 15 | Skill cap ignored | Model asks for a third `on_match` skill; assert refusal and that the turn continues |

## 10 Protobox reuse

Protobox runs agents in TypeScript with the AI SDK. The kernel re-implements its useful behaviours in
Python and leaves the rest.

| Protobox behaviour | Where | In the kernel |
|---|---|---|
| Step cap with a default of 8 | `protobox/services/agent-service/src/tools/services/agent-tool-runner.service.ts:20-21`, `:78-94`; chat caps at 10 (`protobox/services/agent-service/src/chat/chat.service.ts:1608`, `:2004`) | Kept as `budget.max_steps`, default 8 |
| Tool errors returned to the model | `agent-tool-runner.service.ts:187-189` | Kept (section 4.2) |
| Stated text when the last step was a tool call | `agent-tool-runner.service.ts:101-107` | Kept (section 4.4) |
| Mid-stream provider error captured and written in-band | `chat.service.ts:1956-1972` | Kept as `TurnFailed` then `finish` |
| Provider key resolved from workspace secrets | `agent-tool-runner.service.ts:130-138` | Replaced by the AI gateway; the kernel holds no key |
| Tools executed in-process, bypassing an MCP hop | `agent-tool-runner.service.ts:31-35`, `:167-180` | Replaced by the data gateway for every call |
| Dynamic customer context before the stable prompt | `chat.service.ts:1375-1377` | Reversed: stable first (section 3.1) |
| History summarised past a threshold | `chat.service.ts:598-611` | Replaced by truncation from the oldest end (`07` rule 16); see open question 6 |
| Legacy data stream framing (`0:` text, `9:` tool call) | `chat.service.ts:2033`, `:2042` | Replaced by the UI message stream v1 |

Protobox's chat stays in TypeScript for the store edition. ADR-0014 puts its loop in a TypeScript
`agent-kernel` package on AI SDK `streamText` with `stopWhen` and `needsApproval`, with the same four
pieces of our code (`docs/architecture/decisions/agent-loop-library.md:104-110`). Behavioural alignment is kept by shared
fixtures in `packages/contracts`, which has no files yet (`packages/contracts/README.md:3`): each fixture
is a `TurnRequest`, a model cassette, a gateway script and the expected event sequence. The Python
kernel runs all of them. The Protobox suite runs the subset its behaviour covers (step cap, errors to the
model, final-text fallback, stream mapping) through an adapter that maps its request shape onto the
fixture. Stream fixtures can only be shared once the Protobox chat emits the UI message stream v1; until
then the TS side compares tool and text order only. The canonical-JSON input hash function is published
from the same package for both languages.

## 11 Phase 1 and later

| Phase 1 (`14` 9, `docs/specs/runtime-service.md:477`) | Later |
|---|---|
| `TurnRequest`, `TurnResult`, ports, `LoopDriver` on Pydantic AI (section 4.6) | Packaged agents beyond the one phase-1 package |
| Context sections 1, 4, 5, 6, 8, 9; truncation and `context_overflow` | Skills sections 2, 3, 10 with `load_skill` (`docs/specs/skills.md:31-35`, phase 2) |
| Knowledge pre-retrieval and `search_knowledge` with citations and `noAnswer` | Memory recall and `remember` (section 7) |
| Data gateway calls with denies, gated writes as interrupts resumed by R7, workflow tools as child runs | Chat approvals resumed by R14, with step-up (section 5) |
| Interrupts `approval` and `handoff`; `question` as a human step | `question` as a chat reply |
| Step ledger, tool call keys, action ids, retries | Parallel read concurrency above 1 if phase-1 load tests show a need |
| Event stream to the relay for agent Test sheet turns (`07` CD-12) | Chat sessions, `data-review`, `data-interrupt`, `data-skill`, reasoning parts |
| Spans, journal fields, evidence turn record | |
| Fixture suite in section 9 and the shared fixtures in `packages/contracts` | Protobox running the shared fixtures |

## 12 Open questions for the owner

1. Should a retried activity resume from a step ledger kept in Temporal heartbeat details, or re-run the whole turn? Recommended default: the ledger, holding references only, so a retry neither repeats a write nor pays for model steps twice.
2. When a chat approval is decided after the session closed (30 minutes idle), where does the resumed turn run? Recommended default: R14 on a closed session opens a new session pinned to the interrupted turn's version, only to send the approved call and post the result; the next user message uses the live version.
3. How many read tool calls may run at once, and may writes ever run in parallel? Recommended default: up to 4 reads at once; writes, money movements and workflow tools one at a time in model order.
4. Should reasoning text be streamed to staff? Recommended default: no in phase 1; record reasoning token counts only, and decide per alias later.
5. Should memory recall include unverified remembered pages? Recommended default: include the agent's own unverified pages for the same subject, labelled unverified; exclude other agents' unverified pages.
6. Should long transcripts be summarised by a model call, as Protobox does, or truncated? Recommended default: truncate from the oldest end, because a summary is unreviewed model text that would then enter every later turn.
7. Is a 20% reserve of the window for in-loop tool output, and a 25% cap per tool output, right? Recommended default: yes until the phase-1 cost and truncation records show otherwise.
8. In a workflow node with `whenUnsure: ask`, should the question open a human step or fail the node? Recommended default: open a human step on the case, with the question as the task text.
9. Should `packages/contracts` own the shared kernel fixtures and the canonical-JSON hash for both languages? Recommended default: yes.

## 13 Sources

Files opened for this spec, under `<workspace>/ops-ai`: `docs/specs/` `01`, `02`,
`03`, `04`, `07`, `11`, `12`, `13`, `14` and `design-lessons.md`; `docs/architecture/decisions/`
ADR-0005, ADR-0008, ADR-0009 and ADR-0014 (decision and comparison lines only);
`apps/console/src/lib/types/domain.ts`, `chat.ts`, `skills.ts` and `wiki.ts`;
`apps/console/src/lib/api/chat-contract.ts`; `apps/console/src/lib/api/mock/agent-wrappers/index.ts`;
`apps/console/src/components/chat/widgets.tsx`; `packages/contracts/README.md`. In Protobox:
`protobox/services/agent-service/src/chat/chat.service.ts` and
`src/tools/services/agent-tool-runner.service.ts`.

Not opened: the AI SDK UI message stream specification (part names not listed in `07` are
unverified), Pydantic AI's documentation (its behaviour is as ADR-0014 states it), and the other loop
library candidates' documentation.
