# Contracts

Status: not started. No files exist here yet.

This package will hold the API and data contracts shared by the console and the backend services.

| Artifact | Source | Consumers |
|---|---|---|
| OpenAPI 3.1 document | Generated from the console's typed contract (`apps/console/src/lib/api/*-contract.ts`, `apps/console/src/lib/types/`) | Control-plane API, console HTTP client |
| JSON Schema for domain types and workflow definitions | Same | Interpreter (plan and node-settings validation), control plane |
| TypeScript types | Generated from the OpenAPI document and JSON Schema | `apps/console` |
| Python models | Generated from the same | `services/shared` and every service |

CI regenerates the TypeScript types and Python models and fails if either differs from what is
committed, so the console, the services and the contract cannot drift apart. The flow is described
in `docs/backend/overview.md` section 3; the language boundary is set in
`docs/architecture/decisions/ADR-0002-implementation-language.md`.
