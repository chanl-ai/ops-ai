# Control-plane API

Status: not started. No code exists yet.

| Item | Detail |
|---|---|
| Purpose | Serves the API the console calls: the workflow and agent registry, drafts and edit classes, publish requests and the release gate, release pointers, cases, queues and SLAs, reviews and approval tokens, and governance (teams, roles, audit, notifications, API keys, usage). |
| Owns | PostgreSQL system-of-record tables for the registry, cases and evidence index; evidence bundles and audit export in the WORM object store. |
| Depends on | Temporal (starts runs, sends approval updates), `packages/contracts`, `services/shared`, the eval runner (gate results). |
| Specs | `docs/specs/01-agent-builder.md`; `docs/specs/04-evals-and-release.md` (gate, pointers); `docs/specs/08-model-risk.md`; `docs/specs/09-governance-and-admin.md`; ADR-0004, ADR-0006 |

The service map, standards and security boundaries that apply to every service are in
`docs/backend/overview.md`.
