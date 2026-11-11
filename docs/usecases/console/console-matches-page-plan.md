# The console matches the page plan

Status: current. Id: `uc-100`. Service: `console`. Layers: ui.

The Overview shows only what waits on a person: the Human Tasks waiting for the person and the Cases due. Agents has no
Templates tab or "Start from template" until templates have an API. Chat reaches All chats (the conversations) from the sidebar, which lists one area at a time. The
fourth role is called reviewer everywhere a person reads it. Sources: [strategy](../../console/strategy.md),
[page plan](../../console/page-plan.md).

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |

The script starts the stack with the console's mock sign-in (James).

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Open the Overview | "Human Tasks waiting for you" and "Cases due"; no agent task tiles, chart or Workflow health |
| 2 | Click Open all on Cases due | Cases opens |
| 3 | Open Agents | No Templates tab, no Start from template |
| 4 | Click All chats under Chat in the sidebar | `/chat/conversations` opens, and the sidebar lists one area (no Agents row) |
| 5 | Open Settings, Members | Roles read Reviewer, never Approver |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-100-ui.mjs` | failing |

## Non-vacuous check

Each step counts what was removed as well as what stays, so restoring the old Overview tiles, the Templates tab or the
"Approver" label fails it.
