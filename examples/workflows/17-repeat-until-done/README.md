# Repeat until done

A counter fixture hits done. A spin fixture hits the cap.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/workflows/17-repeat-until-done/setup.py
uv run pytest examples/workflows/17-repeat-until-done/test_example.py
```

The full lesson is in [../../../docs/guide/workflows.md](../../../docs/guide/workflows.md).
