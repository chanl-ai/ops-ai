# Chat streaming

Status: current, 2026-10-18.

A chat reply reaches the console as server-sent events from `POST /chat/threads/{id}/messages` with
`Accept: text/event-stream`. Each frame is `data: <json>` followed by a blank line. The event types are
`ChatStreamEvent` in `packages/contracts/src/ops_contracts/chat.py:617`, mirrored in
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
| `done` | `message` | The finished message, as a reload will show it |
| `error` | `message`, `partial`, `code` | The turn failed; `partial` is what was built so far |

## Guarded answers and `replace`

An agent with guardrails streams its answer as it is written, then checks it. When the check finds a blocked topic,
`replace` sends the guardrail's message (or the answer rewritten without the topic) and the console shows that
instead (`apps/console/src/hooks/chat-queries.ts:146`). A guardrail with "Hold until checked" on does not
stream: the answer is shown only after it passes. A turn that ends before its check ran replaces the text with
nothing.

The person saw the first answer before it was replaced, so it is kept on the record. The journal stores it as a
`guardrail_retracted` event (and a never-shown answer as `guardrail_withheld`) with the rule, the stop reason and the
time (`graphs/common.py`). It is never in the stream or in `done`. `GET /chat/threads/{id}` adds it to the message as
`guardrailAudit` only for a reader the roles grid lets view the audit (`can(…, "audit", "view")`; built in, that is
the admin role), and the console shows it under "Audit: what the guardrail took back".

Checks: `tests/api/test_guardrail_audit.py` (the record survives a reload; a builder never gets it), uc-229 ui (an
admin sees it after a reload, a reviewer does not).
