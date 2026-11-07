# ops_files_client: working rules

Status: current.

The typed client other services use to store, read and reference file bytes in files-service by file id, over
`/v1/files` with a service token naming the tenant and team. It does not import `ops_files`: files-service's code
belongs to files-service. Usage example: [README.md](README.md). Package rules and test commands:
[../CLAUDE.md](../CLAUDE.md); repo-wide rules: [../../CLAUDE.md](../../CLAUDE.md#folder-guides).

| Item | Detail |
|---|---|
| Public API | `FilesClient` (`from_settings`, `write`, `get`, `find`, `stream`, `read`, `attach`, `set_data`, `detach`, `report_scan`, `aclose`), `FileInfo`, `StoredFile`, `FileScan`, `FilesRefused`, `FileNotFound`, `FileNotReady` |
| Contract | Every call names the tenant and team; files-service answers 404 for another tenant's or team's file, so a stray id reveals nothing. Bytes are readable only once scanned clean (`FileNotReady` before). Response models ignore unknown fields, so a newer files-service never breaks an older caller |
| Test double | `ops_files_client.testing`: files-service's routes on an httpx `MockTransport`, so a service's tests never boot files-service |
| Depends on | `ops_identity` (`ServiceClient`), `ops_service_kit` |
| Used by | agents-service, documents-service, kb-service, tools-service |
| Tests | None here; covered by the callers' suites and files-service's own (`make test PKG=services/files-service`) |
| Lint, types | `uv run ruff check packages/ops_files_client`, `uv run pyright packages/ops_files_client` |

A hand-written client until clients are generated from each service's `openapi.json`. Routes:
`services/files-service/openapi.json`; docs: [docs/services/files-service/overview.md](../../docs/services/files-service/overview.md).
