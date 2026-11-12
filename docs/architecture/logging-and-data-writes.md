# Logging and data writes

Status: current design, 2026-11-11. Code cited at commit 81c9883a. This page covers how every Python service writes
its log lines, and the one helper a store uses when a person edits a row their team owns. Logging is built; the
write helper is designed and not built yet. The audit log itself is described in
[durability, failure and audit](durability-failure-and-audit.md); table layouts are in [data model](data-model.md).

## Status by part

| Part | Status | Where |
|---|---|---|
| One JSON line per event on stdout, for this code's records and every library's | Built | `packages/ops_service_kit/src/ops_service_kit/logging.py:175` (`configure_logging`) |
| Request, tenant and team ids on every line | Built | `logging.py:83` (`_add_ids`), readers registered with `add_context` (`logging.py:58`) |
| Trace and span ids when an OpenTelemetry span is active | Built | `logging.py:93` |
| Redaction of secrets, query strings, bearer tokens and personal data | Built | `logging.py:117` (`redact`) |
| uvicorn records on the same pipeline, its access log off | Built in every service | e.g. `services/kb-service/src/ops_kb/__main__.py:98`, `services/tools-service/src/ops_tools/__main__.py:332` |
| One `http.request` line per request | Built | `packages/ops_service_kit/src/ops_service_kit/request_timing.py:5` |
| Ruff `T20`, `G` and `LOG` rules | Built | `pyproject.toml:90` |
| A rule that log setup happens only in the kit and event names are literals | Not built | |
| OTLP export to an outside log store | Not built | |
| `ops_store.change`, `create` and `remove` for a person's edit | Not built | |
| One stale-save answer, `409 stale_revision` | Not built | |
| Revision conformance suite on PostgreSQL and SQL Server | Not built | |
| Write rules in `scripts/check_portable_store.py` | Not built | |

## Logging

### How it works

`ops_service_kit.logging` builds every record with structlog and hands it to the standard library root logger. Records
from uvicorn, httpx and SQLAlchemy reach the same formatter through its `foreign_pre_chain`, so the code's own lines
and every library's lines go through one processor chain (`logging.py:133`):

| Order | Processor | Adds or changes |
|---|---|---|
| 1 | `add_log_level`, `TimeStamper(fmt="iso", utc=True, key="ts")`, `add_logger_name` | `level`, `ts`, `logger` |
| 2 | `_add_service` | `service.name`, set once by `configure_logging` |
| 3 | `_add_ids` | `request_id`, `tenant_id`, `team_id` from the context variables their owners keep |
| 4 | `_add_trace` | `trace_id`, `span_id` when a span is active and `opentelemetry-api` is installed |
| 5 | `format_exc_info` | The traceback as text |
| 6 | `redact` | Runs last before rendering, so nothing an earlier step adds escapes it |
| 7 | `_render` | One JSON object; the fields above come first, in that order (`logging.py:34`) |

The ids come from context variables owned elsewhere: the request id in `request_timing`, the tenant and team in
`ops_store`. Each owner registers a reader with `add_context`, so the logging module imports nothing above it.

### Interface

```python
configure_logging(service="kb-service")      # once at start; JSON lines on stdout
log = get_logger(__name__)
log.info("knowledge.source.saved", source_id=sid)
```

```json
{"ts":"2026-11-11T09:14:02.118Z","level":"info","event":"knowledge.source.saved","logger":"ops_kb.store",
 "service.name":"kb-service","request_id":"req_7f3a","tenant_id":"local","team_id":"team_ops","source_id":"src_91"}
```

Every service runs uvicorn with `log_config=None` and `access_log=False`. The request's own line is `http.request`
from `request_timing`, which names the route template and never the raw path and query.

### Redaction

| Rule | Detail |
|---|---|
| Secret-named keys | A key matching `token|secret|passw|authorization|api[-_]?key|[-_]key$|cookie` (`logging.py:39`) has its value replaced by `[redacted]`, at any depth; booleans and numbers under such a key are kept |
| Query strings | A `?name=value` run is removed from every string |
| Bearer tokens | `Bearer <token>` in any string becomes `Bearer [redacted]` |
| Personal data | Every other string goes through `ops_pii.mask` |
| Unmasked fields | `ts`, `level`, `logger`, `service.name`, the three ids, `trace_id`, `span_id` |

`quiet_request_logs` (`logging.py:167`) keeps httpx and httpcore at WARNING, to keep volume down and to keep raw URLs
out of handlers that do not render through the JSON formatter, such as a test's captured records.

### Levels

| Level | Meaning |
|---|---|
| `info` | Something happened that an operator may want to find later |
| `warning` | A person should act |
| `error`, `exception` | A request or job failed |
| `debug` | Off at the default level (`INFO`) |

### Export

Stdout JSON is the export: a host agent, the Fly log shipper or a cloud logging agent reads it. An OTLP exporter is
designed to attach to the same root logger behind `OTEL_EXPORTER_OTLP_ENDPOINT`; it is not built.

### Settings

| Setting | Default | Effect |
|---|---|---|
| `configure_logging(level=)` | `logging.INFO` | Lowest level written |
| `configure_logging(stream=)` | stdout | Where lines go (a test passes its own stream) |
| `OPS_REQUEST_TIMING` | off | Adds timing fields to the request line (`request_timing`, `packages/ops_service_kit/src/ops_service_kit/settings.py:152`) |

### Checks

| Rule | Check | Status |
|---|---|---|
| No `print`, no f-string or `%` log messages | Ruff `T20`, `G`, `LOG` (`pyproject.toml:90`); experiments, migrations and scripts exempt (`pyproject.toml:94-103`) | Built |
| Every line is JSON, carries the ids and has no secret | `packages/ops_service_kit/tests/test_logging.py` | Built |
| `logging.basicConfig`, `uvicorn.run(log_level=...)` or a non-literal event name outside the kit is a finding | An AST rule | Not built |

## Data writes

Designed, not built yet. Store code lives in each service's `store/` package and in `ops_store`, as `.importlinter`
requires. The helper below covers one job: a person edits a row their team owns. Lease fencing, queue claims, seeds,
relay bookkeeping and append-only version tables keep their own write paths.

### Interface (not built)

A table is marked once, the same way `team_owned()` marks team scope (`packages/ops_store/src/ops_store/schema.py:33`):

```python
info={**team_owned(), **revisioned("revision")}          # an existing table passes its column name, e.g. "version"

rev = await change(conn, connections, id=cid, expect=body.revision, values={...}, by=principal.sub,
                   audit=AuditEntry("connection.settings", summary="Changed the base address", detail={...}),
                   event=None)
await create(conn, table, values={...}, by=..., audit=..., event=Event("file.created", key=fid, payload={...}))
await remove(conn, table, id=..., expect=..., by=..., audit=..., event=...)
```

### What `change()` does (not built)

| Step | Behaviour |
|---|---|
| Guard | Refuses a connection with no isolation context |
| Where | Adds `team_visible(table)` and `revision == expect` to the update's `WHERE` |
| Set | Writes `revision + 1`, `updated_by = by`, `updated_at = db_now()` from the database clock |
| Stale | Zero rows updated raises the kit's `Conflict(code="stale_revision")`, answered as 409 |
| Audit | Writes the entry through `ops_store.audit.record` (`packages/ops_store/src/ops_store/audit.py:28`) on the same connection, with the request id from `current_request_id()`; inside platform-service the same call writes `audit_entries` directly |
| Event | Adds the event to the outbox (`packages/ops_store/src/ops_store/outbox.py`) in the same transaction |
| Log | One `store.change` line after commit |
| Returns | The new revision |

### Sequence (not built)

```
console PUT /v1/connections/{id} {revision: 4, ...}
  → service store opens isolated_tx (tenant and team set)
    → change(): UPDATE ... WHERE id=? AND team visible AND revision=4 SET revision=5, updated_by, updated_at=db_now()
       0 rows → 409 stale_revision
    → audit.record(...) into the outbox, same transaction
    → outbox event, same transaction
  → commit → log store.change
  → relay delivers the audit entry to platform-service's one audit log (a few seconds later)
```

### Data model rules (not built)

| Rule | Value |
|---|---|
| Counter column on new tables | `revision`; `version` names only immutable published versions. Existing columns keep their names through `revisioned("version")` |
| New timestamp columns | `DateTime(timezone=True)` filled from `db_now()`; existing string columns keep their type |
| Who | `updated_by`, `created_by` |
| Audit | The one audit log only; pages that read a private audit table read the one log filtered by target |
| Clock | One `db_now()` in `ops_store.dialect` and one `now_iso()` |

### Checks (not built)

| Rule | Check |
|---|---|
| Edits to a revisioned table go through `change()`; no insert into a `*_audit` table outside `ops_store`; no bare `engine.begin()` in a store; no host clock assigned to `updated_at` | Write rules in `scripts/check_portable_store.py`, with a baseline that may only fall |
| `change()` behaves the same on both databases | A revision suite beside the audit suite in `packages/ops_store/src/ops_store/conformance.py`, run on PostgreSQL and SQL Server |
