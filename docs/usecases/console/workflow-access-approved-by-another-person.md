# A workflow's access is decided in Human Tasks by another person

Status: current. Id: `uc-053`. Service: `console`. Layers: ui. Card: c-166.

A request for a workflow's access to a module's operations is a Human Task. The module's Access tab links to it and
decides nothing itself; the module's team decides it in Human Tasks, and the decision reaches the grant.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| platform-service's dev seed | James Richardson (builder) and Priya Shah (admin) on Operations, Nadia Petrov (approver) on Security; password `northfield-demo` |
| agents-service's workflows and Reviews | the ui harness starts it; tools-service reads workflows from it and opens the request there (`OPS_AGENTS_URL`) |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | James publishes a module (Nadia approves its review) and requests a workflow's access to its operation | 201, and the request names its Human Task (`TAR-…`) |
| 2 | James opens the module's Access tab | The request links to `/reviews?review=TAR-…` ("Decide in Human Tasks"); there is no Approve button |
| 3 | Priya follows the link | Human Tasks opens "Let <workflow> use Statements …?" |
| 4 | She approves it | 200; the module's grant is `approved`, decided by her |
| 5 | — | No page errors |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-053-ui.mjs` | passing, `ISOLATED=1 make usecase-test UC=uc-053 LAYER=ui` (2026-10-18) |

## Non-vacuous check

With the Access tab's Approve buttons back on a request that has a Human Task, step 2 fails; with Human Tasks' decision
not applied to the module (`tool_access_reviews.apply` skipped), step 4's grant stays `requested`. Who may decide is
can(reviews.decide) in the team tools-service names, tested in `services/agents-service/tests/api/test_tool_access_reviews.py`.
