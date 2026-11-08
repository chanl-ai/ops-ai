# Services

Deployable services. Each is named after the console section it serves; reusable libraries live in `packages/`.
Full map, layering rules and cross-service contracts: `docs/architecture/service-map.md`. Working rules for agents
and people: `CLAUDE.md` here and in each service folder.

| Folder | State |
|---|---|
| `agents-service/` | Server (`python -m ops_agents.api`, :8700) and worker: chat, agents and workflows registry, graphs on threads, Reviews, widget API |
| `tools-service/` | Server (`python -m ops_tools`, :8720): tool gateway with OPA and approval tokens |
| `platform-service/` | Server (`python -m ops_platform`, :8710 and :8711): sign-in, teams, members and API keys |
| `models-service/` | Server (`python -m ops_models`, :8730): model aliases, keys and routing |
| `kb-service/` | Server (`python -m ops_kb`, :8740): knowledge bases, sources and search on `packages/ops_ingest`; uploads through files-service |
| `files-service/` | Server (`python -m ops_files`, :8750): uploads, downloads and storage settings; backends in `packages/ops_storage` |
| `documents-service/` | Server (`python -m ops_documents`, :8760): extractions and document types, reading bytes through files-service |
| `runner-service/` | Server (`python -m ops_runner`, :8770): code tools' Python on WASM; no database |
| `hitl-service/` | Stub folder; Reviews live in agents-service (see its README) |

`make up` (scripts/stack.sh) starts every server above, the agents worker, the console, the embed app and the dev
fakes; `make migrate` applies each service's own chain (agents, tools, models, kb, platform, files, documents).

Python services share one uv workspace at the repo root. Each has a `Makefile` with `install`, `run`, `test` and
`verify`; `make test PKG=services/<x>` from the root runs one service's tests on a throwaway database.
