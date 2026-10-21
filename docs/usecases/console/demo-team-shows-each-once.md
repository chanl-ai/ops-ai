# The demo team shows each case and workflow once, and its bank data matches its stories

Status: current. Id: `uc-450`. Service: `console`, `agents-service` and the bank stand-in. Layers: ui. Card: c-450.

A walk of staging found each court order notice case open two and three times, two copies of each court order workflow in the run
picker, and Dispute Desk unable to find a credit card charge the seeded dispute names, because the bank stand-in held
only the cardholder's chequing account. This use case checks all three on a deployed console, as a person sees them.

## Preconditions

| Needs | How |
|---|---|
| A deployed console and its demo team | Staging, Harbor & Pine Operations (`team_a0877a1d8907`), seeded per `docs/deploy/fly-staging.md` |
| A person in that team | `STG_EMAIL` and `STG_PASSWORD` in the environment; `STG_ORIGIN` and `STG_TEAM` name the console and team |
| The bank stand-in at the commit that holds the dispute charges | `<your-app>-bank`, deployed from an export of that commit |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| a | Open Cases on the Open view | No subject shows twice; the three court order notice cases show once each |
| b | On Workflows, Start run, then Choose a workflow | No name shows twice; `Levy notice: read the document` and `Levy notice: one debtor` once each |
| c | Ask Dispute Desk about Marcus Bell's Coastal Air charge of 1,240.00 CAD on his credit card | It calls `list_transactions` and names the charge on `VISA-5521`; one chat turn on the team's live model |

`UC450_ONLY=a,b` leaves out step c and its model calls. `UC450_SHOTS=<dir>` saves a screenshot per step.

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| ui | `console/scripts/test-uc-450-ui.mjs` | passing |
