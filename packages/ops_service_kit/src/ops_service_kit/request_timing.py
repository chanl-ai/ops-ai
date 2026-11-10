"""Where a request's time went, and the id that follows it across services.

Every service gets this middleware from `install_error_handlers`. It always keeps or mints the request's id: the error
envelope's requestId and the X-Request-Id sent on by `ServiceClient` read it from here, and the response returns it.
Each request ends in one `http.request` log line, the service's access log (uvicorn's own is off). With
OPS_REQUEST_TIMING on the response also carries Server-Timing (`app` and `db`), which the browser's network panel
shows. Field names follow OpenTelemetry's HTTP conventions so a later exporter can send the same data.

Database time and query count come from the engine listeners `ops_store.open_database` installs, added to the
`RequestTiming` of the request whose task ran the query. Work outside a request (workers, the engine poller) has no
`RequestTiming`, so its queries are never counted to one.
"""

from __future__ import annotations

import re
import time
from contextvars import ContextVar
from dataclasses import dataclass, field

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .ids import new_id
from .logging import add_context, get_logger

log = get_logger(__name__)

HEADER = "x-request-id"
# A caller's own id is kept only in this form: anything else (a line break, a 10 kB value) would land in the logs.
_WELL_FORMED = re.compile(r"[A-Za-z0-9_-]{8,64}")


@dataclass
class RequestTiming:
    request_id: str
    started: float = field(default_factory=time.perf_counter)
    db_ms: float = 0.0
    db_queries: int = 0
    # The verified caller's tenant and team (note_caller), for the request's log line.
    tenant_id: str | None = None
    team_id: str | None = None

    def add_query(self, ms: float) -> None:
        self.db_ms += ms
        self.db_queries += 1


_current: ContextVar[RequestTiming | None] = ContextVar("ops_request_timing", default=None)


def current() -> RequestTiming | None:
    """The request this task is answering, or None outside a request."""
    return _current.get()


def current_request_id() -> str | None:
    timing = _current.get()
    return timing.request_id if timing else None


def note_caller(tenant_id: str | None, team_id: str | None) -> None:
    """The verified caller's tenant and team, for the request's `http.request` line: the middleware writes it outside
    the route's context, where the context the auth dependency set is not visible, but the timing object is shared.
    Called wherever a request's caller is resolved (ops_store.isolation, platform-service's acting team)."""
    timing = _current.get()
    if timing is not None:
        timing.tenant_id, timing.team_id = tenant_id, team_id


def _log_ids() -> dict[str, str | None]:
    return {"request_id": current_request_id()}


add_context(_log_ids)


def request_id_from(header: str | None) -> str:
    """The caller's id when it is well formed, otherwise a new `req_` id."""
    return header if header and _WELL_FORMED.fullmatch(header) else new_id("req")


class RequestTimingMiddleware:
    """Sits just outside `_UnhandledAsEnvelope`, so the 500 envelope is built while the request's id is still set."""

    def __init__(self, app: ASGIApp, *, enabled: bool) -> None:
        self.app = app
        # Server-Timing on responses; the request line is written either way.
        self.enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or [])
        timing = RequestTiming(request_id_from(incoming.get(HEADER.encode(), b"").decode("latin-1") or None))
        token = _current.set(timing)
        status = 500

        async def timed(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-Id"] = timing.request_id
                if self.enabled:
                    app_ms = (time.perf_counter() - timing.started) * 1000
                    headers.append("Server-Timing", f"app;dur={app_ms:.1f}, db;dur={timing.db_ms:.1f}")
                    headers["Timing-Allow-Origin"] = "*"
                    exposed = headers.get("Access-Control-Expose-Headers")
                    headers["Access-Control-Expose-Headers"] = ", ".join(
                        [*([exposed] if exposed else []), "X-Request-Id", "Server-Timing"]
                    )
            await send(message)

        try:
            await self.app(scope, receive, timed)
        finally:
            # Before the reset, so the line carries the request's id.
            _request_line(scope, timing, status)
            _current.reset(token)


def _request_line(scope: Scope, timing: RequestTiming, status: int) -> None:
    route = scope.get("route")
    fields = {
        "http.request.method": scope.get("method", ""),
        # The route's template, never the raw path: a path can carry ids, names and a query string.
        "http.route": getattr(route, "path", None),
        "http.response.status_code": status,
        "duration_ms": round((time.perf_counter() - timing.started) * 1000, 1),
        "db.duration_ms": round(timing.db_ms, 1),
        "db.query_count": timing.db_queries,
        "tenant_id": timing.tenant_id,
        "team_id": timing.team_id,
    }
    log.info("http.request", **fields)
