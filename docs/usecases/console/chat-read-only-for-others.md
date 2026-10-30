# Another person's chat stays private

Status: current. Id: `uc-058`. Service: `console`. Layers: ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| platform-service's dev seed | James Richardson (builder), Maya Okafor (approver), both on team_ops; password `northfield-demo` |
| The scripted model | the ui harness's agents-service |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James creates an agent and chats with it once | a thread he owns |
| 2 | Maya, a teammate, reads `/chat/threads/<thread>` and opens `/chat/<thread>` | 404 from agents-service; the page shows none of James's messages |
| 3 | James opens the same thread | he reads it and the message box is there |

Chat reads are for the chat's own person only, since 2026-10-17, replacing the read-only view for teammates
this use case first proved (an earlier change T021). A review decided from a chat keeps the team rule.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-058-ui.mjs` | passing |

## Non-vacuous check

Step 2 fails if chat reads fall back to the team rule: Maya's read answers 200 and the page shows James's message.
