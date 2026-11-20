# contracts: working rules

Status: current.

`ops_contracts`: hand-written Pydantic models shared across the language boundary and between services. `chat.py`
mirrors `apps/console/src/lib/types/chat.ts` (camelCase on the wire, unknown fields refused); `field_values.py` holds
the field value types a document type and a case type share, with each type's canonical form and how much a value had
to change to reach it; `templates.py` holds the shapes services send each other (`ServiceShape`: `TemplateRequires`,
`Installed` and `CopyRef`, a team's copy of a template), which the sender builds and the reader reads. Package rules and test commands: [../CLAUDE.md](../CLAUDE.md); repo-wide rules:
[../../CLAUDE.md](../../CLAUDE.md#folder-guides).

| Item | Detail |
|---|---|
| Contract | A change to `chat.py` changes `apps/console/src/lib/types/chat.ts` in the same commit; nothing checks the two match yet |
| Contract | A shape one service sends and another reads is a `ServiceShape` in `templates.py`, never a model of the service's own; `scripts/tests/test_no_cross_service_imports.py` fails when a service's `openapi.json` describes one differently or under another name (`make checks`) |
| Used by | `ops_extract` (`field_values`), agents-service, documents-service, tools-service; `ops_service_kit.contract` counts a `ServiceShape` as a typed reply |
| Tests | None here; covered by the callers' suites and the `cross-service` check |
| Types | `uv run pyright packages/contracts` |

Generating TypeScript and Python from one OpenAPI and JSON Schema source is designed and not built. Contract flow:
[docs/architecture/api.md](../../docs/architecture/api.md).

## Engineering standards

The rules the code in this folder is held to, each with a real example from this repository and the check that
enforces it: [layers and ownership](../../docs/architecture/standards/layers.md) (`LY1` to `LY9`), [configuration](../../docs/architecture/standards/configuration.md) (`CF1` to `CF6`). The index of every rule is
[engineering standards](../../docs/architecture/engineering-standards.md); a review cites the rule id.
