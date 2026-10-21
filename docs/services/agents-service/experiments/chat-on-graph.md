# Chat on the graph path

Status: done, 2026-10-11. Tests: `tests/api/test_chat.py`, `test_chat_on_graph.py`, `test_agent_events.py`,
`test_self_approval.py`, `tests/gateway/test_chat_gateway.py`; use cases uc-001, uc-002 (api, ui), uc-009.

## Verdict

Console chat runs on the same path as every workflow, with the console contract unchanged. A conversation is a
thread on the agent wrapper graph, a message is a leased run whose events stream as `ChatStreamEvent`s, an approval
is decided in Reviews, and what a reload shows is rebuilt from the run inputs and the thread event log.

## What holds

| Failure mode | Proof |
|---|---|
| A conversation outside the thread model | It is listed by `GET /v1/threads?graph=agent_wrapper`; each message is an `input` run |
| Two sends interleave on one conversation | A send takes the thread's lease; a held lease answers 409 `run_active` |
| A reload differs from what streamed | Id, content, citations and model of the stored reply equal the `done` frame's |
| Feedback or a regenerate lost on reload | Both are thread events; feedback set and cleared survives a reload; superseded turns drop out |
| An approval decided outside Reviews | The widget action calls decide: a `review_decisions` row, a `decided` event, the resumed run's reply as the continuation |
| A chat money action on a dev token | With the gateway on it runs only after two different approvers; the widget shows `awaiting_second` after the first |
| The asker approving when policy forbids it | The approval carries `requested_by`; `allow_self_approval_in_chat` off refuses with 403 (uc-009) |

## Decisions

| Decision | Detail |
|---|---|
| One translator | `AssistantBuilder` maps events to stream frames and to the stored message, live and on reload |
| Derived ids | A user message keeps the id the send put in the run input; a run's reply is `m_<run id>` |
| History in the input | The facade passes the non-superseded transcript, so regenerate and edit need no checkpoint surgery |
| Chat tables dropped | Migration 0017 drops `threads`, `messages`, `tool_calls`, `widgets`, `interrupts`; `ChatStore` and `turns.py` are gone |
| Dev history discarded | Existing conversations were not copied: they have no checkpoint to resume from, and an old pending approval could not be decided |

## Gotchas

| Gotcha | Consequence |
|---|---|
| A send while an approval is pending | 409 `run_waiting`: decide first. Before, a new message could be sent beside a pending approval |
| A client leaving mid-reply | The run is closed and its reply shows as stopped, as before |
| Reading a conversation rebuilds every message | A few queries per run; fine at demo volume, the first thing to store if lists grow |
| On SQLite the log is written at run end | Chat still streams live; only the stored copy waits for the run to end |
| Per-agent graphs (`agent:<id>`) | In progress in the registry lane; chat threads use `agent_wrapper` until then |
| The ui use case's first run can time out | The console's first compile; reruns pass. The harness, not chat |

## Feeds

`docs/architecture/api.md` (chat routes are a facade over threads) and `runtime.md` (one runtime for chat and
workflows); hunks sent to the docs. Open: the decision on chat self-approval.
