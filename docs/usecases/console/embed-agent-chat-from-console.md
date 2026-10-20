# Embedding the agent chat works end to end from the console

Status: current. Id: `uc-136`. Service: `console` and `agents-service`. Layers: ui.

The 2026-10-18 UX walk found three breaks: the console's snippet belonged to an older loader than the mint keys beside
it, New deployment > Chat widget ended in "Workflow not found", and a viewer was offered Create embed and then refused.
The snippet is now the mint-key flow with the ids filled in, Chat widget picks an agent and creates the embed, and the
embed button follows what the person may do with the agent.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Free use-case ports | agents, platform-service and console (ISOLATED=1 adds 1000) |

The seeded Branch Concierge (`ag_branch`) is Operations' published agent. James builds in Operations, Ravi is its
viewer, Sam is an admin of Security only: he may change Security's records and not this one.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens the agent's Channels tab, Embed on a page, names it and adds an origin | 201; the snippet shows the server's mint request for this deployment with `$OPS_WIDGET_KEY`, the page code for `/embed/v1.js` with the deployment and tenant, no key, and a link to the steps |
| 2 | He opens Channels › Chat embed, Embed on a page, picks Branch Concierge and creates it | 201, a second embed and its snippet |
| 3 | Ravi and Sam open the same agent | Neither sees Embed on a page; Sam's View only notice names Operations; neither notice names its reader |
| 4 | He presses Preview on the first embed | The embed's real chat opens in a frame on the console's origin, on a session minted for him (201) |
| 4b | He sends a message in the Preview | Its thread opens (201); the embed origin is configuration on every stack, so it is not refused |
| 4c | The service refuses a send (403 origin_not_allowed) | The chat keeps the message and shows "Your message wasn’t sent" with the reason, Retry and Dismiss |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-136-ui.mjs` | passing |
