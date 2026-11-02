# Transform a record

One path. `input.a` becomes `output.b`. A missing path fails.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/workflows/13-transform-a-record/setup.py
uv run pytest examples/workflows/13-transform-a-record/test_example.py
```

The full lesson is in [../../../docs/guide/workflows.md](../../../docs/guide/workflows.md).
