# Services

Deployable services. Each is named after the console section it serves; reusable libraries live in `packages/`.
Full map, layering rules and cross-service contracts: `docs/architecture/service-map.md`.

| Folder | State |
|---|---|
| `agents-service/` | Prototype: chat, graphs on threads, leases, timers |
| `tools-service/` | Prototype: tool gateway with OPA and approval tokens |
| `files-service/` | Service logic with tests, no server yet; backends in `packages/ops_storage` |
| `platform-service/`, `hitl-service/`, `models-service/`, `kb-service/` | Not started (`kb-service` will use `packages/ops_ingest`) |

Python services share one uv workspace at the repo root. Each has a `Makefile` with `install`, `run` and `verify`.
