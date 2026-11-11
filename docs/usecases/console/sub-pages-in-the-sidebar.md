# Sub-pages show as rows in the sidebar

Status: current. Id: `uc-047`. Service: `console`. Layers: ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| platform-service's dev seed | James Richardson (builder) and Maya Okafor (reviewer), password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Sign in and open Workflows | the sidebar lists the Build area only (no Cases, Knowledge bases or Activity row); its indented rows are All workflows and Runs (a section with one child also lists its own page); All workflows is the active row |
| 1b | Open Activity | Govern's rows list Tool calls, Audit log, Roles, Tool access and Model inventory and no Runs; Activity is the only active row (a section with several children has no own-page sub-row) |
| 2 | Choose Runs in the sidebar | `/workflows/runs` opens; Runs is the only active row |
| 3 | Hide Activity's pages, then reload | Tool calls stays hidden |
| 4 | Open `/tools/calls` | Activity opens for its current page; Tool calls is the only active row |
| 5 | On Runs, open the page-title switcher and choose All workflows | `/workflows` opens |
| 6 | Maya opens Activity | Tool calls shows and Audit log does not; James has both |

The closed parents are kept in the viewer's browser (`localStorage`, key `ops.sidebar.closed`); without storage every
parent is open.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-047-ui.mjs` | failing |

## Non-vacuous check

Step 1 expects the Build rows alone, so a sidebar that lists every area's sub-rows (as today) fails it; a sidebar with no sub-rows fails it too.
