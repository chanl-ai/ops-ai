# An agent page saves itself and holds its model, knowledge, tools and skills on the main page

Status: draft. Id: `uc-764`. Service: `console`. Layers: ui.

An agent's page has a Settings tab where the model, knowledge, tools and skills sit together, a header that says where
the save stands, and a Channels tab. A change to the name saves a moment after it is made, with no Save press, and the
header goes Unsaved, Saving, Saved. A knowledge base, a tool or a skill is picked on the page and added at once. A draft
agent has nothing to put in channels yet and says so.

## Preconditions

| Needs | How |
|---|---|
| The demo stack with platform sign-in | the ui harness with `platform: true, demo: true`; its knowledge bases and tools are what the pickers search |
| A published agent, a draft agent and a published skill | James makes them through the SDK and the skills route |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James opens the published agent | The header reads Saved; the model, Knowledge, Tools and Skills are on the page |
| 2 | He renames the agent in the title | The header goes Unsaved, then Saving, then Saved; the agent holds the new name |
| 3 | He picks a knowledge base | It is listed and the agent holds it |
| 4 | He picks a tool | It is listed and the agent is granted it |
| 5 | He attaches the published skill | The skill is listed as pinned |
| 6 | He opens Channels | "Ways to reach it" lists Chat, API and SDK, and Embed on a page |
| 7 | He opens Channels of the draft agent | "Publish the agent to put it in channels" shows and the list does not |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `scripts/test-uc-764-ui.mjs` | draft |

## Non-vacuous check

Step 2: with autosave off the header stays Unsaved and the agent keeps its old name, so the last two checks fail.
