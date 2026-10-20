# The channels mock connects a mailbox and a trigger picks it

Status: current. Id: `uc-165`. Service: `console`. Layers: ui.

The maintainers asked for a mock of a workspace Channels app and of how a workflow's Email received trigger reaches a
connected mailbox. `/preview/channels` (development server only) draws it on sample data: a gallery of channel kinds,
every connection with its status, per-kind pages, the connect-a-mailbox form as a page and as a dialog, the mailbox's
settings drawer and page, and a mock of the trigger sheet at `/preview/channels/trigger`. Nothing is stored. The
server routes the real build needs are in `docs/console/channels-preview.md`.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | James Richardson (builder); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens `/preview/channels` | six channel kinds; MCP, Slack and Teams say Coming soon; All connections shows Connected, Needs attention and Paused, with a select column and ids |
| 2 | He opens Email mailbox and Connect a mailbox, picks Gmail and goes on | the settings step shows the address, an app password picked from Secrets, the folder and the replies sender |
| 3 | He tests the connection before picking a secret | sign-in fails and says to pick the secret |
| 4 | He adds a secret from the field, picks the Levies folder and tests again | the new secret fills the field; Sign in, Open Levies and Read the newest message are done and the result says Connected |
| 5 | He connects it | the mailbox's page says no workflow watches it yet |
| 6 | He follows the link to the trigger mock and opens the mailbox picker | the new mailbox is offered |
| 7 | He picks it and saves the version, then opens the mailbox | the mailbox's page lists Levy notice intake, linking to the workflow |
| 8 | On the trigger sheet he opens Connect a mailbox | the same two-step form opens as a dialog; connecting from it fills the trigger's picker |
| 9 | At 400 px he opens the channels, email, agent, activity and trigger pages | nothing scrolls sideways |
| 10 | He reads the channel tabs | each built kind has a dot (email needs attention, chat and API receiving); MCP, Slack and Teams have none |
| 11 | On Email mailbox he presses View activity | the Activity page opens filtered to Email mailbox, every row an email-channel one |
| 12 | He moves Wealth portal from v4 pinned to the latest, then opens Advisor's Helper's Channels tab | v5 is live in Wealth portal too, and no v4 remains |
| 13 | He opens the old Deployments address | it lands on Channels, which says Deployments are now Channels |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-165-ui.mjs` | passing |
