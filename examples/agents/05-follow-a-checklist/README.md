# Follow a checklist

An account-opening guide follows a reusable checklist skill and refuses investment advice. This folder extends the published-agent chat from [01-answer-from-instructions](../01-answer-from-instructions/) (A1). It does not add a second customer tool; that stays in [03-look-up-a-customer](../03-look-up-a-customer/) (A3).

The control fails, then passes: a blocked topic is refused; an allowed checklist question proceeds on the pinned skill.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/agents/01-answer-from-instructions/setup.py
uv run python examples/agents/05-follow-a-checklist/setup.py
uv run pytest examples/agents/05-follow-a-checklist/test_example.py
```

Python uses `ops.agents.chat` plus the public skills and guardrails routes. CLI `opsai agents chat` is built. `opsai chat send` and evaluation are **Planned**.

The full lesson is in [../../../docs/guide/agents.md](../../../docs/guide/agents.md).
