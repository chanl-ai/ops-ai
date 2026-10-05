# Local development stack

Status: planned. The compose file does not exist yet.

`deploy/compose/compose.yaml` will start the backend's dependencies for local development. The
services themselves run on the host with hot reload.

| Container | Purpose | Notes |
|---|---|---|
| Temporal, with its own PostgreSQL | Durable execution | Temporal's database is separate from the platform's |
| PostgreSQL `ops` | System of record: registry, cases, evidence index, call log | |
| PostgreSQL `knowledge` with pgvector | Knowledge index | A separate database, as in ADR-0006 |
| S3-compatible object store | Mail archive, payloads, evidence bundles | Object lock enabled to match the WORM store |
| Portkey gateway | AI gateway data plane | Configured by the key-and-budget service |
| OPA | Policy decisions for the data gateway | Policies loaded from `services/data-gateway/policy/` |

Planned commands:

```bash
docker compose -f deploy/compose/compose.yaml up -d
docker compose -f deploy/compose/compose.yaml down
```

No `.env` file is used. Local settings come from the compose file's defaults and are validated by
each service at start-up (`docs/backend/overview.md` section 6).
