# Schedule an SLA follow-up

Wait until an ISO response date, then open a human task. Approve closes the follow-up. A past date continues at once. A value that is not a date ends as `not_a_date`. Input is an ISO date, not natural language.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/workflows/10-schedule-an-sla-follow-up/setup.py
uv run pytest examples/workflows/10-schedule-an-sla-follow-up/test_example.py
```

After setup:

```bash
cd examples/workflows/10-schedule-an-sla-follow-up
OPS_CONFIG=.ops-profile.json opsai workflows validate resources/workflow.yaml
OPS_CONFIG=.ops-profile.json opsai workflows apply resources/workflow.yaml
OPS_CONFIG=.ops-profile.json opsai workflows run schedule_sla_follow_up --input fixtures/past.json --test --wait
```

| Case | Fixture | Outcome |
|---|---|---|
| Happy | a near-future ISO date | waits, then `closed` after approve |
| Alternate | `fixtures/past.json` | continues at once to a review |
| Failure | `fixtures/invalid.json` | `not_a_date` |

Nodes: `ops.trigger.request` → `ops.data.compute` (`business_days`) → `ops.flow.wait` (`until`) → `ops.flow.humanReview` → `ops.flow.end`. No tool or model. Open the printed `/workflows/definitions/<id>`.

The full lesson is in [../../../docs/guide/workflows.md](../../../docs/guide/workflows.md).
