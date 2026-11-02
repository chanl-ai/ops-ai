# Fire on a clock

Due-at in the past starts one run. A second tick with the same key does not.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/workflows/19-fire-on-a-clock/setup.py
uv run pytest examples/workflows/19-fire-on-a-clock/test_example.py
```

The full lesson is in [../../../docs/guide/workflows.md](../../../docs/guide/workflows.md).
