# Tools service

Every tool call leaves through this service: OPA decides each write against an approval token bound to its input,
and every call is logged. Production runs it as its own process.
Design: `docs/architecture/service-map.md`. Experiment that built it: `docs/services/agents-service/experiments/gateway-approval-token.md`.

## Run it

PostgreSQL and OPA come from the shared dev stack (`make db-up` at the root); `make up` runs this service as `tools`.

```bash
make migrate      # its own chain, version table alembic_version_tools
make run          # http://127.0.0.1:8720 (stop the make up copy first: make stop)
```

## Common tasks

| Task | Command |
|---|---|
| Lint, strict types, tests | `make verify` |
| One test file | `make test T=tests/test_cors.py` |
| Policy | `policy/gateway.rego`, served by OPA from `deploy/compose/compose.yaml` |

Its gateway tests still live in `services/agents-service/tests/gateway` (`make test-gateway`) while `ops_tools`
imports the agents catalogue. Working rules: `CLAUDE.md`; full docs: `docs/services/tools-service/overview.md`.
