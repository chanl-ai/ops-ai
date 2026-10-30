# Every console page reads well on a phone and on a desktop

Status: current. Id: `uc-562`. Service: `console`. Layers: ui. Card: an earlier change.

The console UI sweep (2026-10-29) found ten classes of defect across 50 pages at 1440, 1024 and 390 px. Each is fixed
once in the shared component, so this walk checks one page per class, plus the parts the sweep cannot see, and that the earlier workflow engine no longer shows. The sweep
itself is rerun before and after on the same sample data, and its counts per class are compared; the comparison is
kept with the card's records.

## Preconditions

| Needs | How |
|---|---|
| The demo stack with platform sign-in and a worker | `withUiStack(..., { platform: true, demo: true })`, `stack.startWorker` |
| James and Maya, password `northfield-demo` | The platform seed |
| Two Human Tasks offered as two options, held by Maya, and a case | James starts a credit workflow twice, its person step offering "Give the provisional credit" and "Decline the credit"; Maya assigns both tasks to herself; James opens a case |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Maya opens the first task on Human Tasks and presses Decide before picking | No option is picked; Decide reads "Pick a decision", is disabled and the run still waits; after she picks Reject, Decide is named after it |
| 2 | At 390 px, in light and dark, she opens Agents and scrolls the table to its end; at 1024 and 1440 px she opens six lists | The name is the first column in view and no Id column is drawn; a gradient fade marks the right edge while more columns sit past it and is gone at the end; every search box shows its whole placeholder |
| 3 | At 390 px she opens Cases, Skills and Files, then an agent on a touch screen | The page description reads in full; no header action runs off the screen; the Files view tabs scroll with an edge fade; the agent's page shows its back arrow at rest and a breadcrumb link to Agents |
| 4 | She opens Webhooks in Settings, then her Profile | The breadcrumb ends with the page title "Webhooks" and links to Settings, with no link that fails; Profile has no tab strip, shows her email and not another person's, and her name is read only |
| 5 | She opens Human Tasks, Tool calls and Tools | The second task's queue item shows amount and customer uncut; the sidebar shows one count, on Human Tasks, equal to Assigned to me; Tool calls shows no skeleton and says its totals are not served yet; Tools logs no console error, nests no link, has one open control per row, and a "secret not set" link opens Secrets |
| 6 | She opens Workflows › Runs and Workflows; James opens New workflow | One Runs list with no engine tabs; the Workflows list names no engine and every row opens a current workflow; New workflow asks only a name and what starts it |
| 7 | She opens an old address of a current workflow, one of a workflow from the earlier engine, and an old run link | The first opens the workflow; the second says it is no longer available and links to Workflows; the run link says the run is no longer available above the Runs list |
| 8 | Every call to the agents service answers 503 for 30 seconds while she opens a case | The page says Ops AI can't reach its services instead of going blank, and once the service answers again the case appears with no click |
| 9 | Throughout | No page error |
| 11 | She opens Settings › Workspace › General, then My account | General says in words that parts are sample data and read only, and its sample cards offer no Save or Upload; My account, read from her sign-in, is not marked Preview and says where her name comes from |
| 12 | She opens every Settings page at 1440 × 900 | Each page with sample parts says why in words and offers no Save or Upload there, and the last Settings row (My memory) is not covered |
| 13 | Priya, a team admin, opens a knowledge source's Settings, tries its schedule, then changes its collection and saves | One line says the settings the service does not store can't be saved yet, and the schedule is read only; the save sends only stored fields and its message names the collection |
| 10 | Human Tasks' list is held for 5 seconds while the page loads | No view says it has 0 while the list is held; once it answers the views show their counts |

The non-vacuous checks are step 1 (Decide is pressed while nothing is picked and the run must still wait) and step 2
(the table is scrolled to its end, so a fade that never hides fails).

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-562-ui.mjs` | passing |
