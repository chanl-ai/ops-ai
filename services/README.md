# Services

Status: draft for review. No backend code exists yet; each folder holds a README describing the
planned service.

| Folder | Service | Status |
|---|---|---|
| `control-plane/` | Control-plane API: registry, release gate, cases, governance | Not started |
| `interpreter/` | Workflow interpreter (Temporal worker), node types, agent-block host | Not started |
| `data-gateway/` | Data gateway: tool and knowledge modules, approvals, policy, call log | Not started |
| `ai-gateway/` | Key-and-budget service in front of Portkey | Not started |
| `mailbox-intake/` | Shared-mailbox polling, scan, archive | Not started |
| `knowledge-ingest/` | Knowledge source sync, metadata checks, indexing | Not started |
| `eval-runner/` | Suites, agent evals, evidence bundles | Not started |
| `shared/` | Generated contract models, settings, logging, tracing, clients | Not started |

Service map, contract flow, standards and the walking-skeleton scope: `docs/backend/overview.md`.
