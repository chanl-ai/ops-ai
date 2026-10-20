# kb-service

Department knowledge bases, their file sources, and passages cited by page and section, on :8740. The designed
surface is `.codeloop/wiki/concepts/knowledge.md`; what is built is in `docs/services/kb-service/overview.md`.

```
make db-up                    # from the repo root: the compose PostgreSQL
make -C services/kb-service migrate
make -C services/kb-service run
make -C services/kb-service verify
uv run python scripts/seed_demo_knowledge.py   # the banker demo's bases from seed/*.md (c-058); --agents wires the agents
```
