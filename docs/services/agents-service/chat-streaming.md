# Chat streaming

Status: current, checked against the code on 2026-11-27.

A chat reply reaches the console as server-sent events from `POST /chat/threads/{id}/messages` with
`Accept: text/event-stream`. Each frame is `data: <json>` followed by a blank line. The event types are
`ChatStreamEvent` in `packages/contracts/src/ops_contracts/chat.py:683`, mirrored in
`apps/console/src/lib/types/chat.ts`. A reload rebuilds the same message from the thread's journal
(`api/chat_threads.py`, `AssistantBuilder`), so what streamed and what is stored are one translation.

## Events

| Type | Carries | When |
|---|---|---|
| `start` | `userMessage`, `messageId` | First, once the turn is accepted |
| `status` | `phase`: thinking, retrieving, calling_tool, writing, checking | As the turn moves on; `checking` is the after-answer guardrail check |
| `tool_start`, `tool_end` | `call` | Around each tool call |
| `widget`, `part` | `widget` or `part` | A tool result shaped for display, after its `tool_end` |
| `text` | `delta` | Each piece of the answer as the model writes it |
| `replace` | `text` | The answer streamed so far is replaced by `text` |
| `citations` | `citations` | The passages the answer cites |
| `mode` | `mode` (direct, plan, helpers, sandbox), `reason`, `fixed` | The first time the turn works a way: `direct` when the first model step ends with nothing else used, the others when the plan is accepted, a helper is first asked or the workspace is first used ([automatic mode](../../design/agents-v2/automatic-mode-and-loop-kinds.md)) |
| `plan` | `title`, `steps` (`id`, `text`, `status`: pending, doing, done, skipped, `note`), `revision` | Each time the turn's plan changes, sent whole. A change never runs before one ([automatic mode](../../design/agents-v2/automatic-mode-and-loop-kinds.md)) |
| `agent_asked` | `agentId`, `agentName`, `question`, `status` (started, finished), `summary`, `callId` | Beside the `tool_start` and `tool_end` of a call to a helper agent |
| `handoff` | `to`, `toName`, `message` | A `swarm` agent handed the conversation to another agent; that agent's answer follows in the same message |
| `done` | `message`, `modes` | The finished message, as a reload will show it, and the ways of working the turn used, in order |
| `error` | `message`, `partial`, `code` | The turn failed; `partial` is what was built so far |

## Guarded answers and `replace`

An agent with guardrails streams its answer as it is written, then checks it. When the check finds a blocked topic,
`replace` sends the guardrail's message (or the answer rewritten without the topic) and the console shows that
instead (`apps/console/src/hooks/chat-queries.ts:147`). A guardrail with "Hold until checked" on does not
stream: the answer is shown only after it passes. A turn that ends before its check ran replaces the text with
nothing.

The person saw the first answer before it was replaced, so it is kept on the record. The journal stores it as a
`guardrail_retracted` event (and a never-shown answer as `guardrail_withheld`) with the rule, the stop reason and the
time (`graphs/common.py`). It is never in the stream or in `done`. `GET /chat/threads/{id}` adds it to the message as
`guardrailAudit` only for a reader the roles grid lets view the audit (`can(…, "audit", "view")`; built in, that is
the admin role), and the console shows it under "Audit: what the guardrail took back".

Checks: `tests/api/test_guardrail_audit.py` (the record survives a reload; a builder never gets it), uc-229 ui (an
admin sees it after a reload, a reviewer does not).

## The run trace

`GET /v1/threads/{thread_id}/runs/{run_id}/trace` reads the run's steps back from the thread event log
(`api/run_trace.py`): modes, plans, tool calls, pauses and each turn's model, in the order they were written. Its
`modes` are the run's `mode` events, so the trace and the stream cannot disagree. `GET /v1/agents/loops` lists the
loop kinds with their settings forms; `workflow`, `swarm` and `long_running` are listed with `available: false` until
they are built.
