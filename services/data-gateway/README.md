# Data gateway

Status: not started. No code exists yet.

| Item | Detail |
|---|---|
| Purpose | The only path from workflows to bank systems and knowledge. Owns tool and knowledge modules, module versions, approvals with expiry, the per-call policy decision (OPA, `policy/`), credential resolution, subject binding, approval-token checks on writes and the call log. Adapter code per module kind (MCP, OpenAPI, native) lives in `modules/`. |
| Owns | PostgreSQL (modules, approvals, call log); credentials in the secret store; reads the pgvector knowledge database. |
| Depends on | OPA, the secret store, bank systems, `services/shared`. |
| Specs | `docs/specs/03-data-and-ai-gateways.md` 4.1–4.5, 5.1–5.5; `docs/specs/02-knowledge.md` 5.13; ADR-0005 |

The service map, standards and security boundaries that apply to every service are in
`docs/backend/overview.md`.
