# A Calculate step works out a court order's amount and deadline

Status: passing. Id: `uc-231`. Service: `agents-service`. Layers: api.

The court order demo needs values no system hands over: the amount to hold is the smaller of the ordered amount and
the balance, and
the reply is due twenty working days after the notice was served. The Calculate step (`ops.data.compute`) holds named
formulas over the step's values. A worker runs it and tools-service evaluates the formulas in its sandbox
(`POST /v1/expressions/evaluate`): no files, no network, a time and memory bound, JSON in and out.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| tools-service and agents-service on the run's database | `tools()`, `agents()` |
| A worker process | `python -m ops_agents.api.worker`, started by the script |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Save and publish a workflow with a Calculate step | Saved with every check passing; live |
| 2 | Save one whose formula holds a path (`$.input.balance * 2`) | Refused on `expressions` |
| 3 | Run it on a notice: ordered amount 3250.00 served Friday 2026-10-16, balance 1800 | Completed: amount 1800, short 1450.0, deadline 2026-11-13 |
| 4 | Run it on a notice with no amount | Ends on the error port; the error names the `amount` formula |
| 5 | Call the evaluate route as a service without `tools:view` | 403 |

Formulas read data only as the step's values, by name. The step sends its formulas as the definition holds them, so a
value from the run can never become part of one (`packages/ops_engine/tests/test_compute_step.py`).

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-231-api.py` | passing, `ISOLATED=1 make usecase-test UC=uc-231 LAYER=api` (2026-10-18) |
