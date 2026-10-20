# The live console follows the owner's layout rules

Status: current. Id: `uc-127`. Service: `console`. Layers: ui.

Card c-181: the owner's walk of the console found five layout defects, now rules in
`.codeloop/wiki/rulebook/ui-and-console.md` ("Layout details the owner checks"). This use case checks all five rules on
live pages, one check per rule (rule 2 on two further pages).

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 | `make db-up` |
| platform-service's dev seed | James Richardson (builder, Operations); password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James creates a widget and opens its editor, then the page is read in light and dark | the name field and the textarea are lighter than the page both times (`globals.css`) |
| 2 | He drags the handle between the definition and the preview, reloads, then narrows the window below 1024px | the split moved and is kept; below 1024px there is no handle and the columns stack |
| 3 | At 320px he opens a workflow | no tab label spills its tab, the tab list scrolls sideways, the page does not widen |
| 3b | He opens the agent and a model-inventory entry | each has a drag handle between its columns |
| 5 | He opens a tool module's Operations tab | Import and Add operation are in the page header, once |
| 4 | He opens every list of records (agents, workflows, connections, model inventory, guardrails, widgets, knowledge bases, tool calls, audit log, webhooks, API keys, cases, reviews, secrets, egress) | each starts with select-all, then an Id column with a middle-truncated, copyable id; Secrets and Egress list a key (name, host) that is already the id, so they have select-all only |

## Not covered

| Gap | Where |
|---|---|
| Nested tables inside a record page | knowledge documents, sources, items, history, workflow runs and steps, email tabs, tool executions, account tables, wiki, assurance: they list parts of one record, not the console's lists, and were not changed |
| Rule 2, Retrieval tab and tool workbench | converted to the same split; the Retrieval tab is mounted nowhere and the workbench needs a module, so only the code is covered (uc-010 and uc-101 pass on it) |
| Rule 5, other tabs | Add source, Attach sources, Add case and Import CSV sit in a table's own toolbar or a tab body; only the tool module's Operations row was a button row between sections and is moved |
| Rows to find a copy button in | guardrails, tool calls, cases, reviews and the audit log are empty on the test stack, so only their header (select-all, Id) is asserted |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-127-ui.mjs` | passing (9/9) |

## Non-vacuous check

With `globals.css` and the Agents page at HEAD: rule 1 red (`field 250.43, page 250.43`), rule 3 red (`overflowX: visible`),
rule 4 red (`/agents: idHead false`). With the widget page also at HEAD the run stopped at rule 2, which waits for a
handle that is not there.
