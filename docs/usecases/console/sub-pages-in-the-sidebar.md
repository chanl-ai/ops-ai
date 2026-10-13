# Sub-pages show as rows in the sidebar

Status: current. Id: `uc-047`. Service: `console`. Layers: ui.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| platform-service's dev seed | James Richardson, password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Sign in and open Workflows | the sidebar lists All workflows, Deployments, Collections, Changes, Tool calls, Audit log, Suites and Model inventory as indented rows under their parents (a section with one child also lists its own page); All workflows is the active row |
| 2 | Choose Deployments in the sidebar | `/deployments` opens; Deployments is the only active row |
| 3 | Hide the Wiki's pages, then reload | Collections stays hidden |
| 4 | Open `/knowledge/changes` | the Wiki opens for its current page; Changes is the only active row |
| 5 | On Deployments, open the page-title switcher and choose All workflows | `/workflows` opens |

The closed parents are kept in the viewer's browser (`localStorage`, key `ops.sidebar.closed`); without storage every
parent is open.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-047-ui.mjs` | passing |

## Non-vacuous check

Step 1 fails on a sidebar that renders only top-level items (`app-sidebar.tsx` before c-047): no sub-rows are listed.
