# An agent starts a workflow

Chat grants `workflow:normalize_support_request` and returns the R2 three-node output. The agent does not edit that workflow.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/workflows/01-normalize-a-request/setup.py
uv run python examples/compositions/02-agent-starts-workflow/setup.py
uv run pytest examples/compositions/02-agent-starts-workflow/test_example.py
```

Public SDK: `ops.agents.chat` (prefixes `agent:<id>`).

The full lesson is in [../../../docs/guide/build-with-ops-ai.md](../../../docs/guide/build-with-ops-ai.md).
