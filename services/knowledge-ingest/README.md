# Knowledge ingestion

Status: not started. No code exists yet.

| Item | Detail |
|---|---|
| Purpose | Syncs knowledge sources, enforces required metadata, chunks, embeds through the AI gateway under the ingestion identity, indexes, tracks freshness and maintains the citation index that triggers re-tests. |
| Owns | Separate PostgreSQL instance with pgvector; source copies in the object store. |
| Depends on | Source systems (through the data gateway's network zone), the AI gateway, `services/shared`. |
| Specs | `docs/specs/02-knowledge.md` 4, 5.1–5.8; ADR-0006 |

The service map, standards and security boundaries that apply to every service are in
`docs/backend/overview.md`.
