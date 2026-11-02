# Run an agent in three modes

Start one published agent in stream, wait and background. The same fixture question. No second engine.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/agents/08-run-in-three-modes/setup.py
uv run pytest examples/agents/08-run-in-three-modes/test_example.py
```

The full lesson is in [../../../docs/guide/agents.md](../../../docs/guide/agents.md).
