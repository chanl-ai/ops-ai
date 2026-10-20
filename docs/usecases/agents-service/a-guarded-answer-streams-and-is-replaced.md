# A guarded answer streams as it is written and is replaced when its check fails

Status: passing. Id: `uc-229`. Service: `agents-service`. Layers: ui.

An agent with a guardrail showed nothing until its whole answer and the after-answer check were done, so a reply took
the full model time to appear. A guardrail that does not hold the answer now lets it stream; if the check then finds a
blocked topic, the stream replaces what was shown with the corrected answer or the guardrail's message.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The demo stack on the fake model | the script's `withUiStack({ platform, demo })` |
| The advisor with No investment advice pinned, not held | the demo seed |
| A drifting answer and its correction | the fake rules `UC229 FUND QUESTION` and `Your answer touched a blocked topic` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Maya asks the advisor a fund question | Text frames carry the share advice before any `checking` status |
| 2 | — | One `replace` frame carries the corrected answer |
| 3 | — | The conversation shows the corrected answer and none of the advice |
| 4 | She reloads | The stored message is the corrected answer |
| 5 | — | Maya is a reviewer: no audit of the withdrawn advice on her page or in the stream |
| 6 | Priya, an admin, asks the same in her own chat and reloads | The audit shows the advice as "Shown, then withdrawn" with the rule |
| 7 | — | No page errors |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `agents-service/scripts/test-uc-229-ui.mjs` | passing, `ISOLATED=1 make usecase-test UC=uc-229 LAYER=ui` (2026-10-18) |

## Non-vacuous check

With the kernel's `streaming` set back to "not guarded", step 1 fails (no text frame before the check). With the chat
builder's `text_replaced` case removed (`chat_threads.py`), step 2 fails: no `replace` frame reaches the browser.
Steps 3 and 4 hold either way, because the final `done` frame carries the stored message, which comes from the turn's
result; they guard the stored answer, not the stream. Between the `replace` and `done` frames the console's `replace`
case keeps the screen on the replacement; that window is too short to observe here.
