# Retrieve from knowledge

The handbook already indexed. A question fixture is found. An empty match takes notFound.

```bash
make install && make up DEMO_MODEL=fake && make sample-team
uv run python examples/knowledge/01-search-a-page/setup.py
uv run python examples/workflows/15-retrieve-from-knowledge/setup.py
uv run pytest examples/workflows/15-retrieve-from-knowledge/test_example.py
```

The full lesson is in [../../../docs/guide/workflows.md](../../../docs/guide/workflows.md).
