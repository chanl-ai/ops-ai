# ops_documents_client: working rules

Status: current.

documents-service's client for other services: extract a file, read its full text, and read the team's document
types, each call in the tenant and team the caller acts for, which documents-service reads from the signed token. Package
rules and test commands: [../CLAUDE.md](../CLAUDE.md); repo-wide rules: [../../CLAUDE.md](../../CLAUDE.md#folder-guides).

| Item | Detail |
|---|---|
| Public API | `DocumentsClient` (`from_settings`, `extract`, `read_text`, `document_type`, `document_types`, `template_copies`, `extraction`, `purge`, `aclose`), `DocumentsRefused`, `DocumentNotFound`, `READING` |
| Contract | Scopes default to `documents:view` and `documents:run`; a file over documents-service's synchronous size reads in the background, so an extraction in a `READING` state is polled |
| Test double | `ops_documents_client.testing`: the full-text read on an httpx `MockTransport`, keeping one read per Idempotency-Key (409 on reuse with another request) |
| Depends on | `ops_identity` (`ServiceClient`), `ops_service_kit` |
| Used by | agents-service, tools-service |
| Tests | None here; covered by the callers' suites |
| Lint, types | `uv run ruff check packages/ops_documents_client`, `uv run pyright packages/ops_documents_client` |

Routes: `services/documents-service/openapi.json`; docs:
[docs/services/documents-service/overview.md](../../docs/services/documents-service/overview.md).
