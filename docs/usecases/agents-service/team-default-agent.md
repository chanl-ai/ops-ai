# Chat starts on the team's default agent, which asks specialists

Status: current. Id: `uc-128`. Service: `agents-service`. Layers: api, ui.

People had to pick the right agent before asking anything. A team now has a default agent: a chat started without
choosing one runs on it, it asks the team's other agents when a question needs them, and anyone can hand the chat to a
specialist with @ and come back.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents :8790, platform-service and console for the ui layer (ISOLATED=1 adds 1000) |

The agents service runs on the scripted model, seeded with Branch Concierge (`ag_branch`), Card Dispute Resolver
(`ag_dispute`) and Wire Fraud Sentinel (`ag_fraud`). "call agent__<id> {json}" makes the scripted model call that tool.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Start a chat with no agent before any default is set | 409 `no_default_agent` |
| 2 | Set Branch Concierge as the default, start a chat with no agent | 201, the chat is on Branch Concierge |
| 3 | Ask it to call `agent__ag_dispute` | One tool call, answered by Card Dispute Resolver's own turn, run for the person |
| 4 | Hand the chat to Card Dispute Resolver, send a message, hand it back | The thread names the start agent while handed over; after Back it does not |
| 5 | Reload the chat | Each reply names the agent that wrote it |
| 6 | Grep the default path for an agent id | None: the default comes from the stored setting only |

In the console (ui layer), signed in through platform-service:

| # | Step | Expected |
|---|---|---|
| 1 | James (builder) opens Settings, General | The default agent control is off and says a team admin changes it; his PUT is 403 |
| 2 | Priya (admin) chooses Make default on Branch Concierge in Agents, confirms | The dialog asks "Make Branch Concierge the default for …?"; the row shows Default |
| 3 | Priya opens New chat | Branch Concierge is chosen for her |
| 4 | In the chat, Priya types @Card and picks Card Dispute Resolver | The notice says she is talking to Card Dispute Resolver, with Back to Branch Concierge |
| 5 | She sends a message, then Back | The reply is credited to Card Dispute Resolver; the notice goes away |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-128-api.py` | passing |
| ui | `agents-service/scripts/test-uc-128-ui.mjs` | passing |
