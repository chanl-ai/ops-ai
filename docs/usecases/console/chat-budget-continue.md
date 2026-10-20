# A chat shows when its budget is spent and the person continues

Status: current. Id: `uc-108`. Service: `console`. Layers: ui. Card: c-103.

Every chat conversation starts with its agent's per-conversation caps (model calls and cost; empty fields are the
platform defaults of 200 calls and 5.00, never unlimited). When a cap is reached, the next turn pauses and the chat
shows a card with what was spent, taken from the server's ledger. The conversation's owner continues it, which adds
one more allotment; an admin of its team can raise the caps for that conversation. The server checks who does which.
Design: [chat](../../console/chat.md), interview: c-103 Q1-Q5.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| James (builder), Priya (admin) and Maya on team_ops | platform-service dev seed |

The script starts the stack with platform sign-in on the scripted model and creates an agent whose conversations may
make one model call.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James asks twice in his chat | The second turn shows the budget card "N of 1 model calls" matching the thread's ledger; no Raise for a builder; the message box says the chat is paused |
| 2 | Maya continues James's chat; James raises it, both through the API | 403 each |
| 3 | James presses Continue | 200; the turn answers; the card says it was continued; the box takes messages again |
| 4 | Priya, an admin, asks twice in her own chat and raises the cap to 5 | 200; the card says "raised to 5" |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-108-ui.mjs` | passing |

## Non-vacuous check

Step 2 runs the server's checks with the wrong people; `tests/api/test_chat_budget.py` covers the same with each role.
Removing `ensure_budget` from chat thread creation leaves the conversation without caps and step 1 finds no card.
