# Trigger child workflows

Extract several records from one file and trigger one child workflow per record. The parent waits. A failed child is listed. Siblings still finish.

The folder reuses the team's `levy_notice` / `garnishment_notice` document type and the scripted three-debtor read. Each record maps onto W1 start fields (`customerEmail`, `subject`, `message`). W1 itself never Ends failed, so this folder's child uses those same fields plus `failName` so one sibling can fail.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/workflows/08-one-child-per-record/setup.py
uv run pytest examples/workflows/08-one-child-per-record/test_example.py
```

After setup:

```bash
cd examples/workflows/08-one-child-per-record
OPS_CONFIG=.ops-profile.json opsai workflows validate resources/workflow.yaml
OPS_CONFIG=.ops-profile.json opsai workflows apply resources/workflow.yaml
OPS_CONFIG=.ops-profile.json opsai workflows run one_child_per_record --input fixtures/records.json --test --wait
```

| Case | Fixture | Outcome |
|---|---|---|
| Happy | `fixtures/records.json` | `children_started`, every child succeeded |
| Alternate | `fixtures/partial.json` | `children_started`, one child failed, siblings finished |
| Failure | `fixtures/unreadable.json` | `fanout_failed` |

Nodes: `ops.trigger.request` → `ops.ai.extract` (`many=true`) → `ops.files.setData` → `ops.action.workflow` (`forEach`, `wait=true`) → `ops.flow.end`. Max-items and parent timeout are skipped; they need no new engine setting here.

The full lesson is in [../../../docs/guide/workflows.md](../../../docs/guide/workflows.md).
