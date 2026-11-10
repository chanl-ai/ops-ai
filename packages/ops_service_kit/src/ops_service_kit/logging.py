"""Structured logs: one JSON object per line on stdout, for this code's records and every library's (spec 17 rule 6).

  configure_logging(service="kb-service")      # once, at start
  log = get_logger(__name__)
  log.info("knowledge.source.saved", source_id=sid)
  # {"ts":"…Z","level":"info","event":"knowledge.source.saved","logger":"ops_kb.store","service.name":"kb-service",
  #  "request_id":"req_…","tenant_id":"local","team_id":"team_ops","source_id":"src_…"}

structlog builds our records and hands them to the standard library; uvicorn's, httpx's and SQLAlchemy's records reach
the same formatter through its foreign_pre_chain, so both go through one chain: level and timestamp, the ids, the
active OpenTelemetry span, JSON. The ids come from context variables their owners keep (the request id in
`request_timing`, the tenant and team in `ops_store`): each owner registers a reader with `add_context`, so this module
imports nothing above it. An OTLP exporter can later attach to the same root logger.
"""

from __future__ import annotations

import json
import logging as _logging
import sys
from collections.abc import Callable, Mapping
from typing import TextIO

import structlog
from structlog.stdlib import BoundLogger, ProcessorFormatter
from structlog.typing import EventDict, Processor, WrappedLogger

# The fields every line starts with, in this order; the ids are null when nothing has set them.
SERVICE = "service.name"
IDS = ("request_id", "tenant_id", "team_id")
_FIRST = ("ts", "level", "event", "logger", SERVICE, *IDS, "trace_id", "span_id")
# The handler configure_logging owns on the root logger; a second call replaces it instead of adding another.
_HANDLER = "ops-json"

_service: dict[str, str | None] = {SERVICE: None}
_sources: list[Callable[[], Mapping[str, str | None]]] = []

try:
    from opentelemetry import trace as _otel_trace
except ImportError:  # pragma: no cover - opentelemetry-api is optional; without it no line carries a trace id
    _otel_trace = None


def add_context(source: Callable[[], Mapping[str, str | None]]) -> Callable[[], None]:
    """Registers a reader of ids held in context variables (`request_id`, `tenant_id`, `team_id`). Each line asks every
    reader; a value the call names itself, or an earlier reader found, is kept. Returns what unregisters it."""
    if source not in _sources:
        _sources.append(source)
    return lambda: _sources.remove(source) if source in _sources else None


def _add_service(_: WrappedLogger, __: str, event: EventDict) -> EventDict:
    event.setdefault(SERVICE, _service[SERVICE])
    return event


def _flatten_extra(_: WrappedLogger, __: str, event: EventDict) -> EventDict:
    """`log.warning("x", extra={...})`, the standard library's form, gives the same top-level fields as keywords."""
    # uvicorn's ANSI-coloured copy of its message, for its own console formatter.
    event.pop("color_message", None)
    extra = event.get("extra")
    if isinstance(extra, Mapping):
        del event["extra"]
        for key, value in extra.items():  # pyright: ignore[reportUnknownVariableType]
            event.setdefault(str(key), value)  # pyright: ignore[reportUnknownArgumentType]
    return event


def _add_ids(_: WrappedLogger, __: str, event: EventDict) -> EventDict:
    for key in IDS:
        event.setdefault(key, None)
    for source in _sources:
        for key, value in source().items():
            if value is not None and event.get(key) is None:
                event[key] = value
    return event


def _add_trace(_: WrappedLogger, __: str, event: EventDict) -> EventDict:
    if _otel_trace is None:
        return event
    span = _otel_trace.get_current_span().get_span_context()
    if span.is_valid:
        event.setdefault("trace_id", format(span.trace_id, "032x"))
        event.setdefault("span_id", format(span.span_id, "016x"))
    return event


def _render(_: WrappedLogger, __: str, event: EventDict) -> str:
    ordered = {k: event.pop(k) for k in _FIRST if k in event}
    return json.dumps({**ordered, **event}, default=str, separators=(",", ":"))


# Shared by our records (before they leave structlog) and every other library's (inside the formatter).
_CHAIN: list[Processor] = [
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
    structlog.stdlib.add_logger_name,
    _add_service,
    _flatten_extra,
    _add_ids,
    _add_trace,
    structlog.processors.format_exc_info,
]

structlog.configure(
    processors=[structlog.stdlib.filter_by_level, *_CHAIN, ProcessorFormatter.wrap_for_formatter],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=BoundLogger,
    cache_logger_on_first_use=True,
)


def json_formatter() -> ProcessorFormatter:
    """The formatter configure_logging puts on stdout; a test wraps a stream in it to read exactly what a line says."""
    return ProcessorFormatter(
        foreign_pre_chain=[structlog.stdlib.ExtraAdder(), *_CHAIN],
        processors=[ProcessorFormatter.remove_processors_meta, _render],
    )


def get_logger(name: str) -> BoundLogger:
    """`log.debug|info|warning|error|exception(event, **fields)`: `event` is a literal dotted name, never a sentence
    with values in it. Warning means a person should act; something worth noting is info."""
    return structlog.stdlib.get_logger(name)


def quiet_request_logs() -> None:
    """httpx and httpcore log every request's full URL at INFO, and a URL can carry a resolved secret (a query-string
    API key), so their request lines stay out of the logs; warnings and errors still show."""
    for name in ("httpx", "httpcore"):
        _logging.getLogger(name).setLevel(_logging.WARNING)


def configure_logging(service: str, *, level: int = _logging.INFO, stream: TextIO | None = None) -> None:
    """Once at start: every record in the process, as JSON lines on stdout (`stream` for a test). Run uvicorn with
    `log_config=None` so its loggers reach this handler instead of their own, and `access_log=False`: each request's
    line is `http.request` (`request_timing`), which names the route template, never the raw path and query."""
    _service[SERVICE] = service
    handler = _logging.StreamHandler(stream or sys.stdout)
    handler.set_name(_HANDLER)
    handler.setFormatter(json_formatter())
    root = _logging.getLogger()
    for old in [h for h in root.handlers if h.get_name() == _HANDLER]:
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(level)
    _logging.captureWarnings(True)
    quiet_request_logs()
