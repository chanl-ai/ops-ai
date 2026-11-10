# Read a claim document and open a case

A claim email is extracted. The read is saved on the file. A typed case opens. Low confidence waits for a person. Unreadable ends named.

The folder reuses the team's `levy_notice` document type and the seeded `complaint` case type. Fixtures are text claims the scripted model already knows.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/workflows/06-read-a-claim-and-open-a-case/setup.py
uv run pytest examples/workflows/06-read-a-claim-and-open-a-case/test_example.py
```

After setup:

```bash
cd examples/workflows/06-read-a-claim-and-open-a-case
OPS_CONFIG=.ops-profile.json opsai workflows send-test-email read_claim_and_open_case --event fixtures/claim.json
```

| Case | Fixture | Outcome |
|---|---|---|
| Happy | `fixtures/claim.json` | `opened` |
| Alternate | `fixtures/low.json` | waits, then `opened` after approve |
| Failure | `fixtures/unreadable.json` | `unreadable` |

Nodes: `ops.trigger.email` → `ops.ai.extract` → `ops.files.setData` → optional `ops.flow.humanReview` → `ops.action.openCase` → `ops.flow.end`.

The full lesson is in [../../../docs/guide/workflows.md](../../../docs/guide/workflows.md).
