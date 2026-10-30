"""Where a request's time went, and the id that follows it across services (c-560).

Every service gets this middleware from `install_error_handlers`. It always keeps or mints the request's id: the error
envelope's requestId and the X-Request-Id sent on by `ServiceClient` read it from here, and the response returns it.
With OPS_REQUEST_TIMING on it also writes one JSON object per request on the `ops.request` logger and returns
Server-Timing (`app` and `db`), which the browser's network panel shows. Field names follow OpenTelemetry's HTTP
conventions so a later exporter can send the same data.

Database time and query count come from the engine listeners `ops_store.open_database` installs, added to the
`RequestTiming` of the request whose task ran the query. Work outside a request (workers, the engine poller) has no
`RequestTiming`, so its queries are never counted to one.
"""

from __future__ import annotations

import json
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass, field

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .ids import new_id
from .logging import request_logger

HEADER = "x-request-id"
# A caller's own id is kept only in this form: anything else (a line break, a 10 kB value) would land in the logs.
_WELL_FORMED = re.compile(r"[A-Za-z0-9_-]{8,64}")
_TEAM = re.compile(r"[A-Za-z0-9_-]{1,64}")


@dataclass
class RequestTiming:
    request_id: str
    started: float = field(default_factory=time.perf_counter)
    db_ms: float = 0.0
    db_queries: int = 0

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


def request_id_from(header: str | None) -> str:
    """The caller's id when it is well formed, otherwise a new `req_` id."""
    return header if header and _WELL_FORMED.fullmatch(header) else new_id("req")


class RequestTimingMiddleware:
    """Sits just outside `_UnhandledAsEnvelope`, so the 500 envelope is built while the request's id is still set."""

    def __init__(self, app: ASGIApp, *, enabled: bool, service: str = "") -> None:
        self.app = app
        self.enabled = enabled
        self.service = service
        self.log = request_logger() if enabled else None

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
            _current.reset(token)
            if self.log is not None:
                self.log.info(self._line(scope, incoming, timing, status))

    def _line(self, scope: Scope, incoming: dict[bytes, bytes], timing: RequestTiming, status: int) -> str:
        route = scope.get("route")
        team = incoming.get(b"x-team-id", b"").decode("latin-1")
        return json.dumps(
            {
                "service.name": self.service,
                "http.request.method": scope.get("method", ""),
                # The route's template, never the raw path: a path can carry ids and names.
                "http.route": getattr(route, "path", None),
                "http.response.status_code": status,
                "duration_ms": round((time.perf_counter() - timing.started) * 1000, 1),
                "db.duration_ms": round(timing.db_ms, 1),
                "db.query_count": timing.db_queries,
                "team": team if _TEAM.fullmatch(team) else None,
                "request_id": timing.request_id,
            },
            separators=(",", ":"),
        )
