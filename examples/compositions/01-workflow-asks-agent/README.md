# A workflow asks an agent

A workflow Agent step names the R4 citing agent and keeps its structured cited answer. It does not change that agent's tools or knowledge.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/agents/02-cite-the-handbook/setup.py
uv run python examples/compositions/01-workflow-asks-agent/setup.py
uv run pytest examples/compositions/01-workflow-asks-agent/test_example.py
```

Public SDK: `ops.workflows.validate`, `ops.workflows.apply`, `ops.workflows.run(..., mode="test")`.

The full lesson is in [../../../docs/guide/build-with-ops-ai.md](../../../docs/guide/build-with-ops-ai.md).
