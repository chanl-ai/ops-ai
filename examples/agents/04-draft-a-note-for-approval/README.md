# Draft a note for approval

Extends [Look up a customer](../03-look-up-a-customer/). Reads still run immediately. A write waits: reject leaves no tool call; approve with the exact-input token writes.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/tools/01-find-a-customer/setup.py
uv run python examples/agents/03-look-up-a-customer/setup.py
uv run python examples/agents/04-draft-a-note-for-approval/setup.py
uv run pytest examples/agents/04-draft-a-note-for-approval/test_example.py
```

Python uses `ops.agents.chat` and `ops.tasks.decide`. CLI `ops agents chat` is built. `ops chat send` is **Planned**. Replaying an approval token with a changed body is service-only `POST /v1/calls`, not the public SDK.

The full lesson is in [../../../docs/guide/agents.md](../../../docs/guide/agents.md).
