# Narrow one conversation

A banker narrows one conversation to a model, knowledge and tool subset. Overrides only ever
narrow what the published agent already allows. A widen is refused. Effective settings are on
the thread and on the turn.

This folder reuses the A3 read tool `search_customers` and the A2/A5 handbook. It does not
create a second tool or a second knowledge base. Skills and blocked topics stay in
[../05-follow-a-checklist](../05-follow-a-checklist/). The lookup without an override is
[../03-look-up-a-customer](../03-look-up-a-customer/).

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/knowledge/01-search-a-page/setup.py
uv run python examples/tools/01-find-a-customer/setup.py
uv run python examples/agents/06-narrow-one-conversation/setup.py
uv run pytest examples/agents/06-narrow-one-conversation/test_example.py
```

Python uses the public chat thread and settings routes (`POST /chat/threads`,
`PATCH /chat/threads/{id}/settings`). CLI `opsai chat send` and a high-level
`ops.agents.chat(..., overrides=)` are **Planned**. UI Thread settings is **Built**.

The full lesson is in [../../../docs/guide/agents.md](../../../docs/guide/agents.md).
