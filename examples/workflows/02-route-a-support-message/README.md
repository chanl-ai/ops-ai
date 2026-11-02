# Route an inbound support message

Classify text as billing, technical or cancellation. Below the confidence floor the run ends as `other`. A model answer outside the schema ends as `classify_failed`. One classify call, no write.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/workflows/02-route-a-support-message/setup.py
uv run pytest examples/workflows/02-route-a-support-message/test_example.py
```

After setup:

```bash
cd examples/workflows/02-route-a-support-message
OPS_CONFIG=.ops-profile.json ops workflows validate resources/workflow.yaml
OPS_CONFIG=.ops-profile.json ops workflows apply resources/workflow.yaml
OPS_CONFIG=.ops-profile.json ops workflows run route_support_message --input fixtures/billing.json --test --wait
```

| Case | Fixture | Outcome |
|---|---|---|
| Happy | `fixtures/billing.json` | `billing` |
| Alternate | `fixtures/unsure.json` | `other` (otherwise) |
| Failure | `fixtures/billing.json`, with the classify step's model set to an alias that does not exist | `classify_failed` |

Nodes: `ops.trigger.request` → `ops.ai.classify` → `ops.flow.end`. Open the printed `/workflows/definitions/<id>`.

The first roles lesson reuses this start: [12-roles-refuse-a-start](../12-roles-refuse-a-start/).

The full lesson is in [../../../docs/guide/workflows.md](../../../docs/guide/workflows.md).
