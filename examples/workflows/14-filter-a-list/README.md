# Filter a list

Keep items whose `open` field is true. Counts leave on the kept port.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/workflows/14-filter-a-list/setup.py
uv run pytest examples/workflows/14-filter-a-list/test_example.py
```

The full lesson is in [../../../docs/guide/workflows.md](../../../docs/guide/workflows.md).
