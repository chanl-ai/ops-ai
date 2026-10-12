# Compose stack

Dependencies for local development and demos. The services run on the host.
Deployment targets (VM, Compose, Kubernetes): `docs/architecture/service-map.md` ("Deployment targets").

| Container | Port | Used by |
|---|---|---|
| PostgreSQL 17 | 5477 | agents service, tools service |
| OPA, serving `services/tools-service/policy/` | 8181 | tools service |

```bash
make -C services/agents-service db-up      # or: docker compose -f deploy/compose/compose.yaml up -d --wait
make -C services/agents-service db-down
```

The project name stays `ops-runtime` so the existing data volume is reused. No `.env` file is used.
