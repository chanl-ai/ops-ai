# A workflow's tool step reaches its error and timeout ports on mock answers

Status: passing. Id: `uc-397`. Service: `tools-service`. Layers: api. Card: c-332.

A builder sets an operation's mock answers in test: a status and body, a timeout or a delay, each optionally matching
input values, one the default. The one executor answers a call that says `environment: test` from the first mock that
matches, else the default, before anything is sent; the failure is the one a real answer or a real timeout gives. A
live run, or a call that names no environment, never gets a mock. The tool step's `onTimeout: port` gives it a timeout
port of its own.

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL and OPA | `make db-up` |
| The bank stand-in | `core_bank()`; `GET /accounts/{account_id}` behind its API key |
| agents-service and a workflow worker | `agents()`, `engine_worker()` |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | Add an error mock (503, `ERR-1`), a timeout mock (`SLOW-1`) and a default sample; save and publish the workflow | Listed in order, the sample the default; the workflow goes live |
| 2 | Test runs for `ERR-1`, `SLOW-1` and `CHQ-2219` | Error port with the 503; timeout port with `UPSTREAM_TIMEOUT`; found with the sample |
| 3 | A live run for `CHQ-2219`; read the call log | Found with the bank's own account; each row names test or production |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `tools-service/scripts/test-uc-397-api.py` | passing, `ISOLATED=1 make usecase-test UC=uc-397 LAYER=api` (2026-10-19) |

## Non-vacuous check

Step 2 fails with the executor's mock path removed: the test runs reach the bank, which answers 404
(`.codeloop/evidence/332/uc-397-red-without-mock-answers.txt`). The port itself: `packages/ops_engine/tests/test_tool_timeout_port.py`
(`.codeloop/evidence/332/timeout-port-red.txt`); the environment rule: `services/tools-service/tests/test_mocks.py`
(`.codeloop/evidence/332/test-mocks-red-without-environment-check.txt`).
