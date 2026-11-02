# Look up a customer

Ask for a customer; the agent calls the R1 read tool `search_customers`. This folder does not create a second tool and it does not write.

The tool-call cap is one per turn. A missing customer and a write request take the documented failures.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/tools/01-find-a-customer/setup.py
uv run python examples/agents/03-look-up-a-customer/setup.py
uv run pytest examples/agents/03-look-up-a-customer/test_example.py
```

Python uses `ops.agents.chat`. CLI `ops agents chat` is built. `ops chat send` and evaluation are **Planned**.

The full lesson is in [../../../docs/guide/agents.md](../../../docs/guide/agents.md).
