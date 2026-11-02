# Delegate to a specialist

A triage agent is granted a published specialist as `agent:<id>`. Asking it to research calls that specialist.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/knowledge/01-search-a-page/setup.py
uv run python examples/agents/09-delegate-to-a-specialist/setup.py
uv run pytest examples/agents/09-delegate-to-a-specialist/test_example.py
```

The full lesson is in [../../../docs/guide/agents.md](../../../docs/guide/agents.md).
