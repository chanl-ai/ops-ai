# A builder reads why a test run failed

Status: current. Id: `uc-workflows-2`. Service: `agents-service`. Layers: api, sdk, cli.

A builder test-runs a workflow whose first step reads the customer's email, with a request that names no customer.
The step leaves by its error port to an End marked as a failure. The run fails, and each surface returns the same failure in the one error model: what kind of failure it was, its
code, whether trying again helps, the step that failed, one sentence an end user may read, and the End the run
stopped at.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A builder test-runs the workflow and the run page's route says it failed, at which step and at which End | api | 0-2 | 2 |
| S2 | The sentence for an end user carries no step id, code or exception text, and the details name the End | api | 3-4 | 4 |
| S3 | A script waits for the run with the Python SDK and gets `RunFailed` with the same kind, code, step and End | sdk | 5-6 | 5 |
| S4 | `opsai runs start --wait` exits with the status for a refusal and prints one line saying why | cli | 7 | 7 |
| S5 | `opsai runs show` returns the same failure, with its sentence and details | cli | 8 | 8 |

## Preconditions

| Needs | How |
|---|---|
| PostgreSQL | `make db-up` |
| The run | `make usecase-test UC=uc-workflows-2 LAYER=api` (or `sdk`, `cli`) |

The api stack is agents-service with a workflow worker on a database the run owns, removed when the run ends; the sdk
and cli stacks add platform-service for sign-in. The workflow has no tool or model step, and each run makes only its
own draft workflow and one test run.

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 0 | Save the workflow: Request, Read the customer email, End "Found", End "No email" marked failed | 201, a draft |
| 1 | Start a test run with no customer and read it until it ends | `failed`; the error names "Read the customer email" and "No email" |
| 2 | Read `failure` | kind `refused`, code `ended_as_failure`, not retryable; step `pick`, "Read the customer email" |
| 3 | Read `failure.userMessage` | "This stopped where the workflow says to stop.", with no step id, code, path or exception text |
| 4 | Read `failure.details` | `{"end": "No email"}` |
| 5 | `runs.start(mode="test")`, then `runs.wait(check=True)` | Raises `RunFailed` with the kind, code, retryable and step of step 2 |
| 6 | Read the raised error's `user_message` and the run's `failure.details` | The sentence of step 3 and the details of step 4 |
| 7 | `opsai workflows apply <file>`, then `opsai runs start <workflow> --input <request> --wait` | Exit 3 (refused); one line naming `refused/ended_as_failure`, the step and `not retryable` |
| 8 | `opsai runs show <run> --json` | The failure of steps 2 to 4 |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| api | `agents-service/scripts/test-uc-workflows-2-api.py` | passing |
| sdk | `agents-service/scripts/test-uc-workflows-2-sdk.py` | passing |
| cli | `agents-service/scripts/test-uc-workflows-2-cli.py` | passing |
| ui | none | The failed run page is checked by screenshots at both widths, not by a script |

## Non-vacuous check

`4 the failure's details name the End the run stopped at` fails while the run route drops the error's details. `2`
fails when a step that left by its error port reads as an app failing (`tool_failed`, retryable) rather than the
workflow's own End. `7`
fails when the command line exits 1 for every failure, since the exit status is taken from the failure's kind.
