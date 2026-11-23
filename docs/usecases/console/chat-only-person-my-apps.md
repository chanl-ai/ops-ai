# A person who only chats sees My apps in the sidebar and can chat

Status: draft. Id: `uc-767`. Service: `console`. Layers: ui.

A person whose only role is chat user needs their own app sign-ins as much as a builder does. The sidebar offers them
Chat and My apps, opens My apps on their own sign-ins page, starts a chat and gets an answer, and still offers none of
the builder pages.

## Preconditions

| Needs | How |
|---|---|
| The demo stack with platform sign-in | the ui harness with `platform: true, demo: true` |
| A chat-only person | Lena Brandt, chat user in Operations (`services/platform-service/seed/people.json`) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Lena opens Chat | The sidebar lists Chat and My apps, and none of Agents, Workflows, Cases, Activity or Settings |
| 2 | She presses My apps | The page at `/settings/account/connectors` opens, titled My apps |
| 3 | She asks a question in Chat | A thread opens and the agent answers |
| 4 | She opens the Agents page by its address | The sidebar still offers no Agents row |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `scripts/test-uc-767-ui.mjs` | draft |

## Non-vacuous check

Step 1: before My apps joined the sidebar for chat users, Lena's rows were Chat and New chat only, so the My apps
check fails.
