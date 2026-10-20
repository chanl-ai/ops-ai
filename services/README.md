# Services

Deployable services. Each is named after the console section it serves; reusable libraries live in `packages/`.
Full map, layering rules and cross-service contracts: `docs/architecture/service-map.md`.

| Folder | State |
|---|---|
| `agents-service/` | Server (`python -m ops_agents`): chat, agents and workflows registry, graphs on threads, Reviews, widget API |
| `tools-service/` | Server (`python -m ops_tools`): tool gateway with OPA and approval tokens |
| `kb-service/` | Server (`python -m ops_kb`): knowledge bases, sources and search on `packages/ops_ingest`; uploads through files-service |
| `files-service/` | Server (`python -m ops_files`): uploads, downloads and storage settings; backends in `packages/ops_storage` |
| `documents-service/` | Server (`python -m ops_documents`): extractions and document types, reading bytes through files-service |
| `platform-service/` | Server (`python -m ops_platform`): sign-in, teams, members and API keys |
| `models-service/` | Server (`python -m ops_models`): model aliases and routing; `make up` does not start it, the demo use cases do |
| `hitl-service/` | Stub folder; Reviews live in agents-service (see its README) |
| `knowledge-ingest/` | Empty; ingestion is `packages/ops_ingest`, used by kb-service |

`make up` (scripts/stack.sh) starts platform, agents, tools, kb, files and the console, and `make migrate` applies
each service's own chain (agents, tools, models, kb, platform, files).

Python services share one uv workspace at the repo root. Each has a `Makefile` with `install`, `run` and `verify`.
