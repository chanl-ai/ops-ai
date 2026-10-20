# A banker narrows the agent for a thread within its limits and attaches a file

Status: current. Id: `uc-091`. Service: `console`. Layers: ui. Card: c-071.

A banker opens a chat's settings and sees only what the agent's owner allows: a temperature range, added instructions
and the tools that may be switched off. Switching a tool off means the model is not offered it; every turn records the
settings it ran on; a value outside the limits is refused naming the field. A PDF attached to a message is parsed once
and the answer cites it by page. Design: [chat](../../console/chat.md), decision:
[override model](../agents-service/agent-limits-published.md).

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | the runner picks free ports and a database of its own |

The script starts the agents service on the scripted model and creates its own published agent with limits through
the API; no model key is needed.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Ask "Look up CHQ-2219" | The agent calls lookup_account (the control) |
| 2 | Open Thread settings | No model picker (one model), a temperature slider, "Add instructions", a lookup_account switch |
| 3 | Switch lookup_account off, add an instruction, Save | PATCH answers 200 |
| 4 | Ask again | No lookup_account call; the reply's settings name the tool off and the added instruction |
| 5 | PATCH a temperature of 1.5 through the API | 422 with field `overrides.thread.temperature` |
| 6 | Attach fee-schedule-v2.pdf, ask what a replacement debit card costs | Citation 1 is the file, at "Card fees · p.3" |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-091-ui.mjs` | passing |

## Non-vacuous check

Step 4 compares against step 1 in the same thread: the tool is called before the switch and not after. Removing the
filter in `agent_wrapper._switched_on` fails it, as does dropping the attachment port (the citation step), which
`tests/api/test_chat_attachments.py` also catches.
