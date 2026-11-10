# Logging

Status: current. Every Python service writes one JSON object per line on stdout, through `ops_service_kit.logging`
(structlog 26 on the standard library). Export over OTLP is not built; stdout is what a log shipper reads.

## A line

```json
{"ts":"2026-11-10T03:54:42.660099Z","level":"info","event":"http.request","logger":"ops_service_kit.request_timing",
 "service.name":"platform-service","request_id":"req_uc025_9f031f","tenant_id":"local","team_id":"team_ops",
 "http.request.method":"POST","http.route":"/v1/settings/members/invite","http.response.status_code":200,
 "duration_ms":27.2,"db.duration_ms":11.5,"db.query_count":19,"team":"team_ops"}
```

| Field | Where it comes from |
|---|---|
| `ts`, `level`, `event`, `logger` | The call: UTC time, `debug` to `error` (`exception` logs as `error`), the event name or a library's message, the module |
| `service.name` | `configure_logging(service=...)` in the process's entry point |
| `request_id` | The request's X-Request-Id when well formed, otherwise a minted `req_` id (`request_timing.py`); null outside a request |
| `tenant_id`, `team_id` | The isolation context of the verified caller (`ops_store.isolation`); null in a loop, a seed or before sign-in |
| `trace_id`, `span_id` | Only while an OpenTelemetry span is active; nothing in the repo starts one yet |
| `exception` | The traceback, for `log.exception(...)` or `exc_info=` |
| anything else | The call's keywords, or a standard-library record's `extra` |

Records from uvicorn, httpx, SQLAlchemy and every other library go through the same processors as ours
(`ProcessorFormatter` with `foreign_pre_chain`), so they carry the same fields; their `event` is their message.

## Writing a log call

```python
log = get_logger(__name__)                      # once per module
log.info("knowledge.source.saved", source_id=sid)
log.warning("mailbox.read.failed", mailbox=m, error=type(e).__name__)
log.error("unhandled_error", error=type(e).__name__, exc_info=e)   # outside an except block
```

| Rule | Why |
|---|---|
| The event is a string literal, dotted, with no values in it; values are keywords | A search for one event finds every line of it, and a value cannot fake a line |
| `warning` means a person should act; something worth noting is `info` | Alerts in a log tool fire on warning and above |
| `log.exception` only inside an `except` block; elsewhere `log.error(..., exc_info=e)` | Outside a handler there is no current exception to read |
| Log setup happens only in the kit: no `logging.basicConfig`, no `logging.getLogger` | A second format makes lines a collector cannot parse |
| A service runs uvicorn with `log_config=None, access_log=False` and no `log_level` | uvicorn's records then reach the kit's handler; the request line is `http.request` |

## The request line

`RequestTimingMiddleware` writes one `http.request` line per request, after the response, whatever
`OPS_REQUEST_TIMING` says; that setting only adds the Server-Timing header. It names the route template, never the raw
path or its query string. The middleware runs outside the route's context, so the auth dependency's isolation context
is not visible to it: `request_timing.note_caller(tenant, team)` puts the verified caller's ids on the request's shared
timing object instead. `ops_store.isolation` calls it for every service on `ops_identity`; platform-service, which
resolves its own sessions, calls it where it picks the acting team.

## What is never printed

The `redact` processor runs last before rendering, on every record.

| What | How |
|---|---|
| The value of a key matching `token`, `secret`, `passw`, `authorization`, `api_key` or `apikey`, `cookie` (any case, at any depth) | Replaced with `[redacted]`; numbers and booleans stay, so `input_tokens=12` is kept |
| A query string in any string value or message (`?name=value...`) | Removed up to the next space or quote |
| Emails, SSNs, card, account and phone numbers in any other string | `ops_pii.mask`: `[email]`, `[SSN]`, `[card]`, `[account]`, `[phone]`; ids are left alone |

Names are not masked: no pattern finds them. The fields the kit writes itself (`ts`, `level`, `logger`, the ids) are
not masked.

## Reading the logs

| Task | Command |
|---|---|
| Follow one service of the local stack | `make logs SVC=platform` |
| One request across services | `grep -h '"request_id":"req_…"' .logs/*.log` |
| Pretty-print | `make logs SVC=agents \| jq .` |

## Checks that keep it this way

| Check | Where |
|---|---|
| A structlog, a standard-library and a uvicorn record each render as one JSON line, with `authorization` redacted | `packages/ops_service_kit/tests/test_logging.py` |
| No `print`, no f-string or `%` log messages, standard-library logging mistakes | ruff `T20`, `G`, `LOG` (`pyproject.toml`); scripts, deploy tools, experiments and migrations may print |
| Log setup only in the kit; uvicorn on the kit's handler; literal event names | `check_standards.py` rule 6b (`services/agents-service/tests/unit/test_logging_standard.py`) |
| Every platform-service line parses, and the invite's lines carry its request id, tenant and team | uc-025 api (`docs/usecases/platform-service/audit-log.md`) |

## Gotchas

| Gotcha | Rule |
|---|---|
| pytest's `caplog` keeps records before the formatter, so a library's record there is not redacted | `quiet_request_logs()` still holds httpx at WARNING; a test that scans logs for a secret reads `caplog.text` knowing this |
| A structlog record's `msg` in `caplog.records` is a dict of its fields, not a string | Read fields from it (`packages/ops_store/tests/test_isolation_context.py`) |
| A process that never calls `configure_logging` (a test, a script) prints nothing below WARNING | Call it in every entry point with the service's name |
| `isolation.widen` is logged before its context is set, so its `tenant_id` is null | The line names the tenant in its own `tenant` field |
| platform-service mints its own id for each audit entry instead of the request's | The audit entry's `requestId` does not match its request's log lines yet |

## Not built

An OTLP exporter: it would attach to the same root logger behind `OTEL_EXPORTER_OTLP_ENDPOINT`, and needs the
formatter's processors so that redaction still applies. Trace spans and metrics are out of scope.
