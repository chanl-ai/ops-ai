# Agents service

Agents, workflows, versions, chat, and the runs that execute them. Prototype on seed data.
Full docs: `docs/services/agents-service/overview.md`. Experiments: `docs/services/agents-service/experiments/`.

## Run it

Needs Python 3.12, uv and Docker. Chat needs `OPENAI_API_KEY` in the environment (never in a file).

```bash
make install     # uv sync for the whole Python workspace
make db-up       # PostgreSQL on :5477 and OPA on :8181 (deploy/compose/compose.yaml)
make migrate
make run         # http://127.0.0.1:8700
```

From the repo root, `pnpm dev:runtime` points the console's chat at it.

## Common tasks

| Task | Command |
|---|---|
| Lint, strict types, tests, standards | `make verify` |
| One test | `uv run pytest tests/api/test_chat.py::<test_name>` |
| Regenerate the dependency list | `make sbom` |
