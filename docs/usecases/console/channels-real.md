# Channels on real data

Status: current. Id: `uc-142`. Service: `console` on agents-service `GET /v1/channels`. Layers: ui.

The approved Channels screens (`docs/console/approved/channels/`) were sample data. This walk checks the real pages
against the API: every count and dot on the page is the server's, and Deployments lands on Channels.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens Channels | Six kind cards (MCP, Slack and Teams coming soon), and the connections list in the order `/v1/channels` returns |
| 2 | He reads the tabs | Each built kind's dot is the `kinds` health the server gives it |
| 3 | He opens Email mailbox | The 7-day count is the sum of its mailboxes' activity, and View activity names each mailbox as a source |
| 4 | He opens the old Deployments address, then one naming Wire Fraud Sentinel | It lands on Channels, which says Deployments are now Channels and links to where agents' versions are live; the named one links to that agent's Channels tab by name |
| 5 | On Chat embed he presses Embed on a page | The embed dialog opens with its agent picker |
| 6 | At 400 px he opens the hub and the email page | Nothing scrolls sideways |
| 7 | He moves an embed of Wire Fraud Sentinel to Latest in its row, then opens the agent's Channels tab | The server keeps Latest (or holds it for a review, 202), and the agent's table lists the embed; View activity shows the server's count, the places filter by Status, and the trail names Agents once |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-142-ui.mjs` | passing |
