# Evaluate a known customer

Reuse the A3 look-up agent and score its fixture cases through the public eval route. This folder does not loop `POST /test`.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/tools/01-find-a-customer/setup.py
uv run python examples/agents/03-look-up-a-customer/setup.py
uv run python examples/agents/11-eval-a-known-customer/setup.py
uv run pytest examples/agents/11-eval-a-known-customer/test_example.py
```

Python uses `ops.agents.eval`. CLI `ops agents eval <id> --cases fixtures/cases.json` is built. The console eval-cases surface stays **Planned**.

The full lesson is in [../../../docs/guide/agents.md](../../../docs/guide/agents.md).
