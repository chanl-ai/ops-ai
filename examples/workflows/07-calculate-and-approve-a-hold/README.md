# Calculate and approve an account hold

Match a customer, cap the hold at the first account balance, let a person approve the amount, then place the hold and open a case.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/workflows/07-calculate-and-approve-a-hold/setup.py
uv run pytest examples/workflows/07-calculate-and-approve-a-hold/test_example.py
```

After setup:

```bash
cd examples/workflows/07-calculate-and-approve-a-hold
OPS_CONFIG=.ops-profile.json ops workflows validate resources/workflow.yaml
OPS_CONFIG=.ops-profile.json ops workflows apply resources/workflow.yaml
OPS_CONFIG=.ops-profile.json ops workflows run calculate_account_hold --input fixtures/hold.json --test --wait
```

| Case | Fixture | Outcome |
|---|---|---|
| Happy | `fixtures/hold.json` | waits, then `held` after approve |
| Alternate | `fixtures/missing.json` | `customer_not_found` |
| Failure | `fixtures/failed.json` | `hold_failed` |

Nodes: `ops.trigger.request` → `search_customers` → `ops.data.match` → `list_accounts` → `ops.data.set` → `ops.data.compute` → `ops.flow.if` → `ops.flow.humanReview` → `place_hold` → `ops.action.openCase` → `ops.action.addToCase` → `ops.flow.end`. Open the printed `/workflows/definitions/<id>`.

This folder does not start the run from Ops Assistant or a specialist `workflow:` tool. That is a later lesson.

The full lesson is in [../../../docs/guide/workflows.md](../../../docs/guide/workflows.md).
