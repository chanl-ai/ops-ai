# The chat thread on AI Elements

Status: current. Id: `uc-074`. Service: `console`. Layers: ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| The scripted model | the ui harness's agents-service |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Open a thread with the fraud agent on the People knowledge base and ask for the daily wire limit | the answer streams into the conversation log; its `[1]` draws as a citation button, and no raw marker shows |
| 2 | Open the citation | its source passage shows |
| 3 | Ask to look up CHQ-2219 | a `lookup_account` card in the success state; opening it shows the input |
| 4 | Get a reply carrying a remote image | no request reaches the image's host; the image shows as "[Image blocked: balance chart]" |

The thread view is composed from AI Elements blocks behind `components/shared/chat-blocks.tsx` (c-055 T002): the
conversation, messages and their actions, the streamed markdown response, the tool card and the message box.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-074-ui.mjs` | passing |

## Non-vacuous check

Step 1 fails if the response renders markers as text: `[1]` shows in the log and no citation button exists. Step 4
fails with Streamdown's default image handling: the browser requests `exfil.test`.
