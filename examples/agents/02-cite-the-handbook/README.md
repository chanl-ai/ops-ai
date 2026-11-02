# Cite the handbook

Ask a question the R1 account-opening handbook answers and see the cited section. This folder attaches that handbook. It does not create a second knowledge base.

A question the page does not answer takes the documented no-answer (`expected/missing.json`).

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/knowledge/01-search-a-page/setup.py
uv run python examples/agents/02-cite-the-handbook/setup.py
uv run pytest examples/agents/02-cite-the-handbook/test_example.py
```

Python uses `ops.agents.chat`. CLI `ops agents chat` is built. `ops chat send` and evaluation are **Planned**.

The full lesson is in [../../../docs/guide/agents.md](../../../docs/guide/agents.md).
