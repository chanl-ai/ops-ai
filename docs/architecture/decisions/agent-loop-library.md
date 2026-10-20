# ADR-0014 Agent loop library

Status: option, not decided. No ADR has been confirmed by the owner as of 2026-10-10; each one records the options, a scoring and a recommendation, and the build keeps a seam open so the choice can differ per enterprise deployment.

## Context

The agent loop is the code that runs one agent step inside one workflow node, and one chat turn. It
builds the context (agent version instructions, pinned skills, memory, knowledge citations), calls
the model through the AI gateway ([ADR-0008](ai-gateway.md)), executes tool calls through
the data gateway with approval tokens, stops on a condition, streams AI SDK UI message parts
([ADR-0009](chat-experience.md), [`07`](../../../.codeloop/wiki/concepts/agent-chat.md) CD-11, CD-12), pauses
for an in-turn human approval and resumes, and records a trace.

Fixed by earlier decisions:

| Constraint | Source |
|---|---|
| The loop runs in the agent-block host or the chat turn worker, as a Temporal activity; workers hold no model keys, no credentials and no user token | [`14`](../../../.codeloop/wiki/concepts/runtime-service.md) 3.1, 3.2 |
| Model calls go to the key-and-budget service as `POST /v1/chat/completions` with `model` = alias; stable instructions first for prompt caching | `14` 5.4, ADR-0008 |
| The transcript in PostgreSQL schema `chat` is the record; Temporal history holds references only. So the library must own no persistence | `07` CD-1, CD-2 |
| Approval binds to a hash of the complete tool payload; only a host-native button decides; the requester cannot approve | `07` CD-3, CD-6, CD-7; [design lessons](../../../.codeloop/wiki/concepts/design-lessons.md) rank 7 |
| Trust facts come from the run context, never from model-visible text; the gateway binds the subject of a call | Design lessons ranks 1 and 2 |
| Configured agents (`AgentVersion`) run on this loop; packaged agents (`AgentPackage`, for example an existing LangGraph agent) run their own code on the same host | [`01`](../../../.codeloop/wiki/concepts/agent-builder.md) 4.5, [ADR-0003](workflow-definition-format.md) |
| Language: Python per [ADR-0002](implementation-language.md), under reconsideration in favour of TypeScript | ADR-0002 |

An activity cannot wait days for a person, so "pause and resume" means: the loop ends the activity
(or the chat turn) with the pending tool calls, the workflow waits for the decision as a signal or
update, and a new activity resumes from the message history plus the decision. A library fits when
its pause is a return value and its resume is a new call with the same messages.

The existing TypeScript service today: `ai` ^6.0.116 and `@ai-sdk/mcp` ^1.0.25. The playground streams with
`streamText` and `stopWhen: stepCountIs(10)` over tools from `createMCPClient`, and writes its own
wire format (`0:` text, `9:` tool call, `a:` result, `e:` finish), which is not the UI message
stream. Delegated agents run `generateText` with a step cap (default 8) and return tool errors to the
model. Approvals are out of band: the tool executor stores a snapshot, returns `PENDING_APPROVAL`,
and an approve call replays the tool server-side. No in-turn interrupt exists.

## Options

| Option | What it is | Version (date) | Licence | Language |
|---|---|---|---|---|
| AI SDK tool loop | `streamText`/`generateText` with `stopWhen`; the `ToolLoopAgent` class exists in v6 ([AI SDK 6][aisdk6]); tools take `needsApproval` (static or a function of the input) | `ai` 6.0.303 on the `ai-v6` tag (2026-10-09); v7.0.137 is `latest`, 7.0.0 released 2026-06-25 ([npm][npm-ai], [AI SDK 7][aisdk7]); all versions read from npm and PyPI on 2026-10-10 | Apache 2.0 | TS |
| Own loop, TS | An `agent-kernel` package we own: context builder, tool compiler, approval binding, trace, over AI SDK core `streamText` | n/a | Ours | TS |
| LangGraph.js | Graph runtime; `interrupt()` with `Command` resume needs a checkpointer and thread id ([HITL][lgjs-hitl]) | 1.4.21 (2026-10-07); 1.0.0 on 2025-10-18 ([npm][npm-lgjs]) | MIT | TS |
| Mastra | Agent framework built on AI SDK, with workflows, memory and evals | `@mastra/core` 1.75.0 (2026-10-07); 1.0.0 on 2026-01-20 ([npm][npm-mastra]) | Apache 2.0 outside `ee/`; `ee/` needs an enterprise licence in production ([licence][mastra-lic]) | TS |
| OpenAI Agents SDK, JS | Agent runner with handoffs, guardrails, MCP, approvals and serialisable `RunState`; Temporal TS integration is pre-release, with nested approvals unsupported ([Temporal][t-oai-ts]) | `@openai/agents` 0.20.0 (2026-10-08) | MIT | TS |
| Pydantic AI | Typed agent library; deferred tools end a run with the calls needing approval, and a new run resumes with the decisions ([deferred][pyd-deferred]); native AI SDK UI stream adapter, with `sdk_version=6` enabling tool-approval streaming ([adapter][pyd-vercel]); optional `TemporalDurability` runs the agent in workflow code ([Temporal][pyd-temporal]) | 2.55.0 (2026-10-09) ([PyPI][pypi]) | MIT | Python |
| OpenAI Agents SDK, Python | As the JS SDK; Temporal integration GA for Python in March 2026 per ADR-0002 | 0.23.1 (2026-10-02) | MIT | Python |
| LangGraph Python | Graph runtime; Temporal's plugin runs nodes as activities and maps `interrupt()` to signals, Python only, preview (ADR-0001, ADR-0002) | 1.2.14 (2026-10-06) | MIT | Python |
| Own loop, Python | Our loop over the `openai` client pointed at the gateway, plus our own UI stream encoder | n/a | Ours | Python |
| Microsoft Agent Framework | Successor to Semantic Kernel and AutoGen; .NET and Python; no TypeScript per a secondary summary, **unverified** ([MAF][maf-lang]) | 1.21.0 (2026-10-08); 1.0 on 2026-04-03 | MIT | Python, .NET |

Temporal also ships `@temporalio/ai-sdk` 1.24.0, in public preview, which wraps AI SDK model calls as
activities so the loop runs in workflow code, and relays stream deltas through Workflow Streams
([Temporal][t-aisdk]). AI SDK 7 adds `WorkflowAgent`, which persists state to durable storage between
steps ([AI SDK 7][aisdk7]). Both move the loop or its state out of the single activity that `14`
specifies, so they are scored only as later options.

## Scoring

Criterion 6 is scored as maturity and maintenance in the option's own language, so that Python
options are not marked down for not being TypeScript.

| Option | Activity, no persistence 15 | Interrupt, token bound 15 | UI stream 10 | MCP 10 | Gateway 10 | Maturity 10 | Licence 10 | Existing TypeScript reuse 10 | Tracing 10 | **Total** |
|---|---|---|---|---|---|---|---|---|---|---|
| AI SDK tool loop (TS) | 5 | 4 | 5 | 4 | 5 | 5 | 4 | 5 | 4 | **4.55** |
| Own loop over AI SDK core (TS) | 5 | 4 | 5 | 4 | 5 | 4 | 4 | 5 | 4 | **4.45** |
| Pydantic AI (Py) | 5 | 5 | 5 | 5 | 5 | 5 | 4 | 1 | 4 | **4.40** |
| Own loop over `openai` (Py) | 5 | 4 | 2 | 3 | 5 | 3 | 5 | 2 | 3 | **3.65** |
| Mastra (TS) | 3 | 3 | 4 | 4 | 5 | 4 | 3 | 3 | 4 | **3.60** |
| OpenAI Agents SDK (Py) | 4 | 4 | 2 | 5 | 4 | 4 | 3 | 1 | 3 | **3.40** |
| OpenAI Agents SDK (JS) | 4 | 4 | 2 | 5 | 4 | 3 | 3 | 2 | 3 | **3.40** |
| LangGraph Py + Temporal plugin | 3 | 4 | 2 | 4 | 4 | 5 | 4 | 1 | 3 | **3.35** |
| Microsoft Agent Framework (Py) | 3 | 3 | 2 | 4 | 4 | 4 | 4 | 1 | 4 | **3.20** |
| LangGraph.js | 2 | 3 | 3 | 4 | 4 | 4 | 4 | 1 | 3 | **3.05** |

Evidence, one line per criterion:

| Criterion | Evidence |
|---|---|
| Activity, no persistence | AI SDK, Pydantic AI and own loops are plain function calls whose state is the message list. OpenAI Agents needs a `RunState` string stored by us. LangGraph interrupts need a checkpointer and thread id; its plugin instead moves the graph into workflow code. Mastra's suspend and memory use its storage layer (**unverified** in detail). |
| Interrupt, token bound | Pydantic AI validates arguments before the approval gate and re-validates on resume ([Temporal page][pyd-temporal]). AI SDK `needsApproval` sees the input, ends the stream in `approval-requested`, and resumes from an approval response ([AI SDK 6][aisdk6]). Binding the token to a hash of the input is our code in every option. |
| UI stream | AI SDK and the TS kernel emit it natively. Pydantic AI ships `VercelAIAdapter`. LangGraph, OpenAI Agents, MAF and an own Python loop need an encoder we write and keep current with the protocol. Mastra's AI SDK compatibility is **unverified**. |
| MCP | OpenAI Agents and Pydantic AI treat MCP servers as first-class toolsets; AI SDK MCP is `@ai-sdk/mcp`, used by the existing TypeScript service today. An own Python loop uses the MCP SDK directly. |
| Gateway | All accept an OpenAI-compatible base URL. OpenAI Agents defaults to the Responses API, so it must be set to Chat Completions for the key-and-budget service (**unverified** that Portkey OSS serves Responses). |
| Maturity | Release dates in the options table. OpenAI Agents is pre-1.0 in both languages. |
| Licence | All permissive. Mastra has an `ee/` licence. OpenAI Agents is a model vendor's SDK, a vendor-direction risk. |
| Existing TypeScript reuse | Only the AI SDK options reuse the existing chat and tool-runner code; Mastra reuses tool definitions in part (**unverified**); Python options reuse the design only. |
| Tracing | AI SDK emits OpenTelemetry spans and v7 adds `@ai-sdk/otel` ([AI SDK 7][aisdk7]). Pydantic AI instruments through OpenTelemetry (**unverified** in this session). OpenAI Agents traces to OpenAI by default, which a bank must switch off (**unverified**). |

## Decision

**Python runtime (lead, per ADR-0002): Pydantic AI**, called as a plain agent run inside the
agent-block host and chat turn activities, without `TemporalDurability` in phase 1. Approvals use
deferred tools: the run ends with `DeferredToolRequests`, the activity returns them, the workflow
waits for the decision, and a new activity resumes with `DeferredToolResults`. Streaming uses
`VercelAIAdapter` with `sdk_version=6`, so the console's `useChat` needs no adapter (CD-11). Our
code around it: the context builder (stable fragments first), the model provider pointed at the
key-and-budget service with the run context token, the approval binding (sha256 of the canonical
tool input in the drafted action, verified by the data gateway on execution), and the trace writer
to the run journal. Packaged LangGraph agents keep running as `AgentPackage` on the same host.

**TypeScript runtime: AI SDK core `streamText` with `stopWhen` and `needsApproval`, inside an
`agent-kernel` package we own.** The library supplies the loop, MCP and the UI message stream; the
kernel supplies the same four pieces of our code. We do not adopt `ToolLoopAgent` as the public API,
because the kernel needs to own composition order and the trace. For the existing TypeScript service this means extracting
its loop into the kernel, replacing the
custom `0:/9:/a:/e:` wire format with the UI message stream, and adding in-turn approval beside the
existing out-of-band `PENDING_APPROVAL` path. Its chat service then calls the kernel, and Ops AI uses
the same package. The two TS rows are within 0.1 of each other; the kernel row is the AI SDK row
plus code we already run.

## Consequences

### Strongest counter-argument and our answer

**"LangGraph has the largest ecosystem, and Temporal ships a plugin for it. Use it in Python."** The
plugin is Python-only and in preview (ADR-0002). It runs each graph node as an activity with the
graph in workflow code, which replaces `14`'s single agent activity and adds history per step. Run
outside the plugin, interrupts need a checkpointer, which conflicts with CD-2. It has no AI SDK UI
stream encoder. Existing LangGraph agents still run unchanged as packaged agents.

For TypeScript, the counter-argument is "adopt Mastra or the OpenAI Agents SDK to get memory, evals
and an agent class". Each brings its own memory, storage or trace export that we would have to turn
off, and the controls that matter here (gateway, approval binding, trust facts from the run context)
sit outside any library.

### Cost of the language choice for this component

Python gives a strong library with a native UI stream adapter and no reuse of existing TypeScript code.
TypeScript gives the same capability by extracting code an existing service runs today. Either way the
approval binding, context builder and trace are ours.

### What would change this decision

- `VercelAIAdapter` falls behind the UI message stream version the console needs. Then write our own
  encoder in Python or move the chat turn worker to TypeScript.
- Temporal's durability integrations reach GA and we choose loop-in-workflow for long agent runs.
  Then Pydantic AI `TemporalDurability` (Python) or `@temporalio/ai-sdk` (TS) replaces the plain run.
- ADR-0002 flips to TypeScript. Then the TS pick applies and Pydantic AI is not used.

## Phase 1 vs later

| Phase 1 | Later |
|---|---|
| Pydantic AI plain runs in the agent-block host and the agent Test sheet turn (CD-12); deferred-tool approvals with hash binding; `VercelAIAdapter` stream; OpenTelemetry spans to the bank's collector; tool-call suite per alias | Chat sessions with in-turn approvals (`07` phase 2); evaluate `TemporalDurability` for long agent runs; `agent-kernel` extraction for an existing TypeScript service if it needs in-turn approval or the language flips |

## Open questions for the owner

1. Is ADR-0002 final at Python? Default: yes, and this ADR's Python pick applies.
2. Which AI SDK major does the console's `useChat` target? Default: v6, the version `VercelAIAdapter`
   supports for approvals, until a v7 adapter is confirmed (**unverified**).
3. Extract an `agent-kernel` for an existing TypeScript service now? Default: no while Ops AI is Python; do it
   when that service needs in-turn approval.
4. May any library export traces outside the bank (Logfire, LangSmith, OpenAI traces)? Default: no;
   OpenTelemetry to the bank's collector only.
5. Does the Portkey OSS gateway need to serve the Responses API? Default: no; Chat Completions only.

## Sources

[aisdk6]: https://vercel.com/blog/ai-sdk-6
[aisdk7]: https://vercel.com/changelog/ai-sdk-7
[npm-ai]: https://www.npmjs.com/package/ai
[npm-lgjs]: https://www.npmjs.com/package/@langchain/langgraph
[npm-mastra]: https://www.npmjs.com/package/@mastra/core
[lgjs-hitl]: https://docs.langchain.com/oss/javascript/langgraph/human-in-the-loop
[mastra-lic]: https://mastra.ai/docs/license
[t-aisdk]: https://docs.temporal.io/develop/typescript/integrations/ai-sdk
[t-oai-ts]: https://docs.temporal.io/develop/typescript/integrations/openai-agents
[pyd-deferred]: https://ai.pydantic.dev/deferred-tools
[pyd-vercel]: https://pydantic.dev/docs/ai/integrations/ui/vercel-ai/
[pyd-temporal]: https://pydantic.dev/docs/ai/capabilities/durable_execution/temporal/
[pypi]: https://pypi.org/project/pydantic-ai/
[maf-lang]: https://devblogs.microsoft.com/foundry/microsoft-agent-framework-reaches-release-candidate/
