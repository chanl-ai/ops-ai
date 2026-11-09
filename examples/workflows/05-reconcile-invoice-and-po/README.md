# Reconcile an invoice with a purchase order

Read the invoice and the PO in parallel, join them, and merge trusted fields. An exact match ends as `matched`. A disagreement on amount, currency, vendor or PO number waits for a person, then records the resolution on a case. A missing record ends as `lookup_failed`.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/workflows/05-reconcile-invoice-and-po/setup.py
uv run pytest examples/workflows/05-reconcile-invoice-and-po/test_example.py
```

After setup:

```bash
cd examples/workflows/05-reconcile-invoice-and-po
OPS_CONFIG=.ops-profile.json opsai workflows validate resources/workflow.yaml
OPS_CONFIG=.ops-profile.json opsai workflows apply resources/workflow.yaml
OPS_CONFIG=.ops-profile.json opsai workflows run reconcile_invoice_po --input fixtures/match.json --test --wait
```

| Case | Fixture | Outcome |
|---|---|---|
| Happy | `fixtures/match.json` | `matched` |
| Alternate | `fixtures/mismatch.json` | waits, then `resolved` after approve |
| Failure | `fixtures/missing.json` | `lookup_failed` |

Nodes: `ops.trigger.request` → two `ops.action.tool` reads → `ops.flow.join` → `ops.flow.if` → `ops.data.combine` (`onDisagreement: port`) → `ops.flow.humanReview` → `ops.action.addToCase` → `ops.flow.end`. Open the printed `/workflows/definitions/<id>`.

The full lesson is in [../../../docs/guide/workflows.md](../../../docs/guide/workflows.md).
