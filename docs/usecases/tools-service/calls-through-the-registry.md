# A tool call runs through the registry and is logged with its caller

Status: current. Id: `uc-011`. Service: `tools-service`. Layers: api.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | An agent's registry read runs and its output comes back with masked fields masked | api | 1 | 1 |
| S2 | A write with no approval, input missing a required field and a tool no module holds are each refused before anything leaves the gateway | api | 2-4 | 3 |
| S3 | Every call, refused ones too, is logged with the calling service, the agent and the run | api | 1-5 | 5 |
| S4 | Once Security publishes an operation's rate and amount limits, calls past them are refused and logged | api | 6-7 | 7 |
| S5 | The console's test panel and mock refuse exactly the amounts the gateway refuses | api | 7-9 | 9 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL :5477 and OPA :8181 | `make db-up` |
| Nothing else | The script starts tools-service on its own database, seeded with the console's modules, and agents-service for Reviews; Core banking's operations answer from their stub |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `POST /v1/calls` for `get_loan_account` as workflow `dispute_email`, an identity OPA has registered | 200; the output's `borrower.sin` is `[redacted]` |
| 2 | `update_address` with no approval token | 403: the registry says it is a write |
| 3 | `get_loan_account` without `loanAccountId` | 422 naming the field; nothing runs |
| 4 | `drop_tables` | 403: no module holds it |
| 5 | `GET /v1/executions?thread=<run>` | four rows; the first names the calling service as subject (taken from its service token, never the body), the agent as actor, and the run; the other three are `denied` |
| 6 | Set `get_loan_account`'s rate limit to 1 a minute and publish it with step 7's edit; Security approves in Reviews; then call it three times | calls run on the published operations until the approval; then at least one 429 `RATE_LIMITED` with `resetAt`, logged `denied` |
| 7 | Show `transfer_funds` (limit 2,500) and call it with amount 3,000 | 403 `amount_over_limit` before the policy is asked, logged `denied` |
| 8 | The console test panel with the same amount | deny `constraint`, the same verdict |
| 9 | Amounts 3,000, 2,500, 100, `"abc"`, none and -5,000,000, through the gateway and through the console mock's rule (`amount.ts`, run by node) | both refuse exactly 3,000, `"abc"`, none and the negative |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-011-api.py` | passing |

In the console: the module's Activity tab shows each call with who asked, the decision and how it ended (uc-086's ui script, step 11).

## Non-vacuous check

`a registry read runs (200)` paired with the three refusals: a gateway that refused everything fails the read, and
one that ran everything fails the refusals. `every call is logged, refused ones too` fails if a refusal leaves no row.
an earlier change: `a call past the operation's rate limit is refused` fails if the gateway counts nothing, and `the console mock
refuses exactly the amounts the gateway refuses` fails if either side's amount rule drifts.
