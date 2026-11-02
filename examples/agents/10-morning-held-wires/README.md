# Morning held-wires review

One published agent. A due tick on the existing timer clock starts one job. The report is the run output.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/agents/10-morning-held-wires/setup.py
uv run pytest examples/agents/10-morning-held-wires/test_example.py
```

The full lesson is in [../../../docs/guide/agents.md](../../../docs/guide/agents.md).
