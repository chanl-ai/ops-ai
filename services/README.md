# Services

Status: draft for review. Each folder holds a README describing the planned service; only
`knowledge-ingest/` and `files/` have code so far.

| Folder | Service | Status |
|---|---|---|
| `control-plane/` | Control-plane API: registry, release gate, cases, governance | Not started |
| `interpreter/` | Workflow interpreter (Temporal worker), node types, agent-block host | Not started |
| `data-gateway/` | Data gateway: tool and knowledge modules, approvals, policy, call log | Not started |
| `ai-gateway/` | Key-and-budget service in front of Portkey | Not started |
| `mailbox-intake/` | Shared-mailbox polling, scan, archive | Not started |
| `knowledge-ingest/` | Knowledge source sync, metadata checks, indexing | Library in progress: parsing, splitting, metadata, dedupe, rules; no server |
| `files/` | Files service: uploads, downloads, dedupe, scanning hook, retention and legal holds over S3 or Azure Blob | Library in progress: service, S3, Azure Blob and local stores; no server or PostgreSQL repository |
| `eval-runner/` | Suites, agent evals, evidence bundles | Not started |
| `shared/` | Generated contract models, settings, logging, tracing, clients | Not started |

Service map, contract flow, standards and the walking-skeleton scope: `docs/backend/overview.md`.
