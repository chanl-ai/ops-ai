# ADR-0006 Data stores and evidence

Status: accepted (draft for review). Formerly DR-6.

## Context

The platform needs a system of record for the registry (workflows, agents, versions, pointers,
approvals), for cases, queues and SLAs, and for evidence attached to versions. Audit logs must be
immutable with retention and legal hold. Knowledge needs vector search scoped by department.

## Options

### System of record

| Option | Relational integrity for pins and approvals | Bank operability | Row-level scoping by department | Score |
|---|---|---|---|---|
| **PostgreSQL** | Strong: foreign keys from version pins to immutable rows, transactional pointer moves | Widely run in banks | Row-level security | **5** |
| MongoDB (used by an earlier internal product) | Weak across documents; pointer moves and audit rows are not one transaction without care | Common | Application-enforced | 3 |
| Temporal visibility store as the record | Not designed for it; retention-bound | n/a | No | 1 |
| The bank's case system (ServiceNow, Salesforce, Pega) as case record | Strong inside that product | Already run | Product-specific | 3 (see ADR-0007) |

## Decision

| Data | Store | Notes |
|---|---|---|
| Registry, versions, pointers, approvals, gate policies | PostgreSQL schema `registry` | Published rows immutable; edits create rows (the configuration-overwrite lesson in [design lessons](../../specs/design-lessons.md)) |
| Cases, queues, SLAs, drafted actions, decisions | PostgreSQL schema `cases` | SLA deadlines stored here and enforced by Temporal timers; the case row is what people see, the timer is what fires |
| Evidence index | PostgreSQL schema `evidence` | Points to bundles by digest |
| Evidence bundles (definition, test results vs baseline, approvals, reviewer notes) | WORM object storage | One bundle per version; immutable once written |
| Mail archive, attachments, large payloads | WORM object storage | Referenced from Temporal history, never inlined |
| Audit log | Append-only PostgreSQL table with a hash chain, exported continuously to WORM storage and to the bank's SIEM | Covers registry changes, approvals, pointer moves, gateway decisions, break-glass |
| Run history | Temporal (operational, retention-bound) plus a run journal written by activities into PostgreSQL | The journal is the durable record of what each step did; Temporal history is operational and retention-bound, so the journal serves as the long-term evidence store |
| Knowledge items, chunks, embeddings, query records | PostgreSQL with pgvector, schema `knowledge`, in a separate database on its own instance | Same engine, backups and operating model as the main database; separate so bulk re-indexing cannot slow case writes and SLA updates. See below |

WORM storage: S3 Object Lock in compliance mode means no user, including root, can delete or shorten
retention, legal holds have no expiry, and Object Lock has been assessed for SEC 17a-4, CFTC and
FINRA environments ([S3 Object Lock][s3-lock]). The bank's on-prem equivalent must offer the same
three properties; which product it is depends on the bank ([open question 5](../overview.md#open-questions)).

### Vector store

| Option | When it is right | Cost |
|---|---|---|
| **pgvector in a separate PostgreSQL database** | Default. Department scope is a SQL filter in the same query as the vector search; iterative index scans help filtered queries return enough results ([pgvector][pgvector], v0.8.7, HNSW and IVFFlat) | No new system |
| Dedicated vector database | When measured recall or latency at the bank's corpus size fails with pgvector | New system to secure and run |
| Existing enterprise search (the bank's search engine or M365 search) | When a department's documents are already indexed with permission trimming | Integration only; citations and freshness depend on that system |

All three sit behind the same knowledge-module interface in the data gateway, so the choice can
differ per module and change later without touching workflows. The ten knowledge requirements
(metadata, scope, precedence, citations, freshness) are enforced in the module layer rather than in the vector
store (`02`).

## Consequences

### What would change this decision

- The bank's standard operational database is not PostgreSQL (for example Oracle). Then the same
  schemas on that database, with a separate vector store.
- Retention rules require run history itself, not the journal, as evidence. Then Temporal history is
  exported to WORM at run close.

## Phase 1 vs later

| Phase 1 | Later |
|---|---|
| PostgreSQL schemas for registry, cases, evidence index and audit; a second PostgreSQL instance with pgvector for the first knowledge bases; WORM bucket for mail, payloads and evidence; audit export to SIEM | Dedicated vector store or enterprise-search modules where measured; legal-hold tooling in the console |

## Sources

[pgvector]: https://github.com/pgvector/pgvector
[s3-lock]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html
