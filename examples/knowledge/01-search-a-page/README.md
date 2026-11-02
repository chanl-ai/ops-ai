# Search a handbook page

Add one handbook page and search it. This folder reuses the account-opening handbook.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/knowledge/01-search-a-page/setup.py
uv run pytest examples/knowledge/01-search-a-page/test_example.py
```

Python uses the public SDK (`ops.knowledge.search`) and `fixtures/query.json`. The CLI `ops knowledge search` is **Planned**.

The full lesson is in [../../../docs/guide/build-with-ops-ai.md](../../../docs/guide/build-with-ops-ai.md).
