# Wait for an external verification result

Start a KYC check, release the worker, and resume when the provider posts the result. A clear callback ends as `clear`. An ambiguous result waits for a person, then `flagged` or `clear`. A missing subject or a timeout ends as `check_failed`.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/workflows/09-wait-for-verification/setup.py
uv run pytest examples/workflows/09-wait-for-verification/test_example.py
```

After setup:

```bash
cd examples/workflows/09-wait-for-verification
OPS_CONFIG=.ops-profile.json ops workflows validate resources/workflow.yaml
OPS_CONFIG=.ops-profile.json ops workflows apply resources/workflow.yaml
OPS_CONFIG=.ops-profile.json ops workflows run wait_for_verification --input fixtures/clear.json --test --wait
```

| Case | Fixture | Outcome |
|---|---|---|
| Happy | `fixtures/clear.json` | waits, then `clear` after a callback |
| Alternate | `fixtures/review.json` | waits, then `flagged` after reject |
| Failure | `fixtures/missing.json` | `check_failed` |
| Failure | `fixtures/timeout.json` | waits, then `check_failed` |

Nodes: `ops.trigger.request` → `ops.action.tool` (`start_check`) → `ops.flow.waitFor` (`verification.result`) → `ops.flow.switch` → `ops.flow.humanReview` → `ops.flow.end`. Resume uses `POST /v1/runs/{id}/steps/wait/resume` with the step token. Open the printed `/workflows/definitions/<id>`.

The full lesson is in [../../../docs/guide/workflows.md](../../../docs/guide/workflows.md).
