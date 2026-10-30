# A builder tests an agent in the right panel of its page, with the chat page's components

Status: passing. Id: `uc-253`. Service: `agents-service`. Layers: ui. Card: an earlier change.

The agent page's right column is a panel with four tabs. Test is a real chat on a thread the server marks test
(an earlier change), drawn with the chat page's own message list, composer and cards (`components/chat/thread-messages.tsx`).
Why explains the selected reply. Versions and Used in hold what the right column showed before. Run as is gone.

## Preconditions

| Needs | How |
|---|---|
| The demo stack on the fake model, with platform sign-in | `withUiStack(..., { platform: true, demo: true })` |
| James Richardson, a builder of team_ops | the platform dev seed |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Open Advisor's Helper | The test panel sits beside the settings; nothing offers Run as |
| 2 | Ask the UC229 fund question in the Test tab | The reply streams in the panel, with the chat page's guardrail note |
| 3 | Open Why | It names the knowledge searched, the tools called and "No investment advice" |
| 4 | Open Versions, then Used in | Version history; the workflows using the agent and its recent runs |
| 5 | At 400 px, press Test | The panel comes into view with its composer editable, and the test is still there |
| 6 | — | No page errors |

Screenshots at 1280 and 400 px go to the card's evidence folder, or to `UC253_SHOTS` when set.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `agents-service/scripts/test-uc-253-ui.mjs` | passing, `ISOLATED=1 make usecase-test UC=uc-253 LAYER=ui` (2026-10-18) |
