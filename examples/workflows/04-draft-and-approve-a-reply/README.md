# Draft and approve a customer reply

A complaint email is classified and summarized. A reply is drafted. Nothing is sent until a person approves the exact text. Reject leaves `declined` with no write. A review that expires (`onTimeout: expire`) leaves `escalated` with no write. A body the fake model cannot classify ends `draft_failed`.

This folder extends the R3 draft-and-approve Example with the human-review control failing (timeout) and then passing (approve). The write is the existing platform `send_reply` tool, approved by the review.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/workflows/04-draft-and-approve-a-reply/setup.py
uv run pytest examples/workflows/04-draft-and-approve-a-reply/test_example.py
```

After setup:

```bash
cd examples/workflows/04-draft-and-approve-a-reply
OPS_CONFIG=.ops-profile.json opsai workflows send-test-email draft_and_approve_reply --event fixtures/complaint.json
OPS_CONFIG=.ops-profile.json opsai workflows decide <task-id> approve
```

The full lesson is in [../../../docs/guide/workflows.md](../../../docs/guide/workflows.md).
