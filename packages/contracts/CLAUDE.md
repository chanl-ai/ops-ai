# contracts: working rules

Status: current.

`ops_contracts`: hand-written Pydantic models shared across the language boundary. `chat.py` mirrors
`apps/console/src/lib/types/chat.ts` (camelCase on the wire, unknown fields refused); `field_values.py` holds the
field value types a document type and a case type share, with each type's canonical form and how much a value had to
change to reach it. Package rules and test commands: [../CLAUDE.md](../CLAUDE.md); repo-wide rules:
[../../CLAUDE.md](../../CLAUDE.md#folder-guides).

| Item | Detail |
|---|---|
| Contract | A change to `chat.py` changes `apps/console/src/lib/types/chat.ts` in the same commit; nothing checks the two match yet |
| Used by | `ops_extract` (`field_values`), agents-service, documents-service; `ops_service_kit` lists it as a dependency without importing it |
| Tests | None here; covered by the callers' suites |
| Types | `uv run pyright packages/contracts` |

Generating TypeScript and Python from one OpenAPI and JSON Schema source is designed and not built. Contract flow:
[docs/architecture/api.md](../../docs/architecture/api.md).
