# Contracts

API models shared by the console and the services. Today `ops_contracts` holds hand-written Pydantic models that
mirror `apps/console/src/lib/types/chat.ts` (camelCase on the wire, unknown fields refused). Generating TypeScript and
Python from one OpenAPI 3.1 and JSON Schema source, with a CI check that both match, is designed and not built.

Contract flow: `docs/architecture/api.md`. Language boundary: `docs/architecture/decisions/implementation-language.md`.

```bash
uv run pyright packages/contracts     # from the repo root; part of make verify
```
