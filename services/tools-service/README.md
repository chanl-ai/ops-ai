# Tools service

Every tool call leaves through this service: OPA decides each write against an approval token bound to its input,
and every call is logged. Production runs it as its own process.
Design: `docs/architecture/service-map.md`. Experiment that built it: `docs/services/agents-service/experiments/gateway-approval-token.md`.

## Run it

PostgreSQL and OPA come from the shared dev stack.

```bash
make -C ../agents-service db-up migrate
make run          # http://127.0.0.1:8720
```

## Common tasks

| Task | Command |
|---|---|
| Lint, strict types, tests | `make verify` |
| Policy | `policy/gateway.rego`, served by OPA from `deploy/compose/compose.yaml` |

Its tests and tables still live in `services/agents-service` (`tests/gateway`, `migrations/`) until migrations split
per service.
