# An agent's Channels tab shows every real place it answers

Status: current. Id: `uc-130`. Service: `agents-service`. Layers: api, ui.

The agent's Deployments tab mixed mock rows with the real embeds, so a builder could not tell where the agent answers.
The tab is now Channels: whether the agent is the team's chat default, its embeds with their sites, keys and usage, and
the workflows that call it, all from agents-service. An embed can be paused, or retired for good.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents :8790, platform-service and console for the ui layer (ISOLATED=1 adds 1000) |

The agents service runs on the scripted model with the seeded Wire Fraud Sentinel (`ag_fraud`) published.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Make two embeds of `ag_fraud` with `POST /v1/channels` (`type: chat`), mint a key on the first, start one conversation through it | 201s |
| 2 | List the agent's embeds: `GET /v1/channels?type=chat&agentId=ag_fraud` | The first shows 1 conversation in 7 days, a last-used time and 1 active key; the second 0, none and 0 |
| 3 | Retire the first | 200 with `retiredAt` |
| 4 | Mint a session on it, resume it | 409 `widget_retired` both times |
| 5 | List again, then with `includeRetired=true` | The first is left out, then listed with `embed.retiredAt` |

In the console (ui layer), signed in through platform-service:

| # | Step | Expected |
|---|---|---|
| 1 | James (builder) opens Wire Fraud Sentinel, Channels | The tab is called Channels; Chat, the two embeds with sites, keys and usage, and Versions live (where each version answers); every embed row is an agents-service id |
| 2 | Ravi (viewer) opens the same tab | No Retire or Pause buttons |
| 3 | James retires the first embed and confirms | The row shows Retired and no actions; its server session is refused with 409 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `console/scripts/test-uc-130-api.py` | passing |
| ui | `console/scripts/test-uc-130-ui.mjs` | passing |
