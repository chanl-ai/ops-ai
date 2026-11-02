# A builder validates, applies and test-runs the three-node workflow

Status: current. Id: `uc-623`. Service: `agents-service`. Layers: sdk, cli. Card: an earlier change (R2).

A builder copies `examples/workflows/01-normalize-a-request`, validates and applies the same YAML, and test-runs a
support request through Python, TypeScript, and `ops workflows`. A request missing `customerEmail` is refused with
that schema path. Setup prints the definition URL the console opens.

## Stories

| # | Story | Layer | Steps | Proved by |
|---|---|---|---|---|
| S1 | A builder runs folder setup, then validate, apply and a test run through the Python SDK, and sees outcome accepted | sdk | 1-2 | 2 |
| S2 | They do the same through the TypeScript SDK on the same definition | sdk | 3 | 3 |
| S3 | They validate, apply and `run --test` the same YAML with `ops workflows` | cli | 7-9 | 9 |
| S4 | A request missing customerEmail is refused with the schema path | sdk | 4 | 4 |
| S5 | A second setup prints FOUND; the printed UI path opens that definition | sdk | 5-6 | 6 |

## Preconditions

| Needs | How |
|---|---|
| Local fake stack | `make up DEMO_MODEL=fake` |
| Sample team | `make sample-team` |
| Public Python and TypeScript SDKs | `ops_ai` and `@chanl-ai/ops-ai` against the running services |

## Steps and expected results

| # | Step | Expected |
|---|---|---|
| 1 | `uv run python examples/workflows/01-normalize-a-request/setup.py` | Prints READY; prints `/workflows/definitions/<id>` |
| 2 | `uv run pytest examples/workflows/01-normalize-a-request/test_example.py` | Passes; public SDK validate/apply/test-run returns `accepted` |
| 3 | `node examples/workflows/01-normalize-a-request/test_example.mjs` | Exits 0; validate/apply/test-run returns `accepted` |
| 4 | Python SDK test-run without `customerEmail` | 422 `invalid_input` with path `customerEmail` |
| 5 | The same setup again | Prints FOUND |
| 6 | Open the printed `/workflows/definitions/<id>` | The console shows that definition |
| 7 | `ops workflows validate resources/workflow.yaml` | Exit 0; prints valid |
| 8 | `ops workflows apply resources/workflow.yaml` | Exit 0; prints the workflow id |
| 9 | `ops workflows run <id> --input fixtures/valid.json --test --wait` | Exit 0; outcome accepted |
| 10 | `ops workflows run <id> --input fixtures/missing-email.json --test` | Exit 1; output names `customerEmail` |

## Acceptance layers

| Layer | Script | State |
|---|---|---|
| sdk | `agents-service/scripts/test-uc-623-sdk.py` | current |
| cli | `agents-service/scripts/test-uc-623-cli.py` | current |

## Non-vacuous check

Step 2 fails while `test_example.py` only asserts `outcome:` in YAML. Step 4 fails when `POST /v1/runs` accepts a
payload that omits `customerEmail`. Step 10 fails when the CLI prints a success for that payload.
