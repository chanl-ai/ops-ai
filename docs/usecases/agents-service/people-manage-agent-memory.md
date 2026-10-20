# People see, correct, forget and export what an agent remembers

Status: current. Id: `uc-135`. Service: `agents-service` and `console`. Layers: ui.

An agent that remembers people between chats (uc-134) is only trusted if people can tell when it saves something
and change what it keeps. Each reply that saved something now says so, and the chat's What I remember sheet lists
what the agent keeps about the person, with correct, forget and export.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents, platform-service and console (ISOLATED=1 adds 1000) |

The agents service runs on the scripted model, which saves "timezone: Eastern" from "My timezone is Eastern". The
seeded Branch Concierge (`ag_branch`) has memory on.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James sends "Hi. My timezone is Eastern." to the Branch Concierge | Under the reply: "Saved to memory: timezone: Eastern" |
| 2 | He reloads and opens What I remember from that line | The sheet lists timezone: Eastern |
| 3 | He corrects it to Pacific | The row shows Pacific, marked Corrected by you; the API returns one memory, Pacific |
| 4 | He exports | my-memories.json holds the memory and the correction in its history |
| 5 | He forgets it | The sheet says nothing is remembered; the API returns none |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `agents-service/scripts/test-uc-135-ui.mjs` | passing |
