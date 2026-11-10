# Answer from instructions

Ask a published agent one question and read the reply. This folder reuses the R1 chat surface (`ops.agents.chat`). It has no tools and no knowledge base.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/agents/01-answer-from-instructions/setup.py
uv run pytest examples/agents/01-answer-from-instructions/test_example.py
```

Python uses `ops.agents.chat` and `fixtures/question.json`. CLI `opsai agents chat` is built. `opsai chat send` is **Planned**.

The full lesson is in [../../../docs/guide/agents.md](../../../docs/guide/agents.md).
