# Run and review controls show only to roles that can use them

Status: current. Id: `uc-123`. Service: `console`. Layers: ui. Card: c-123.

The server refuses a run start to anyone but a builder or admin, and a cancel or a decision to anyone the rules do not
allow (c-122). The console hides those controls from the same people, reading the server's flags where the rule needs
the record (c-123), so nobody presses a button that answers 403.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA | `make db-up` |
| platform-service's dev seed | James Richardson (builder) and Ravi Menon (viewer) on team_ops; password `northfield-demo` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Ravi, a viewer, opens a workflow every team sees | no Start run or Test run button |
| 2 | James, a builder, opens the same workflow | the run button is there |
| 3 | James starts a live run; Ravi, then James, open it | Cancel run is hidden from Ravi and shown to James, its starter |
| 4 | James requests publish of an agent; Ravi, then Maya (reviewer), open the review | Ravi sees "A reviewer or admin of the team that reviews this decides it." and no Approve; Maya gets the decision form |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-123-ui.mjs` | passing |

## Non-vacuous check

Steps 1, 3 and 4 fail if the console ignores the server's flags (evidence/123/red-run.txt): the run button, Cancel run
or Approve show to Ravi.
