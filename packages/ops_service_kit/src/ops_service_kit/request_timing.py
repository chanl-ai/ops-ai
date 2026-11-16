"""Where a request's time went, and the id that follows it across services.

Every service gets this middleware from `install_error_handlers`. It always keeps or mints the request's id: the error
envelope's requestId and the X-Request-Id sent on by `ServiceClient` read it from here, and the response returns it.
Each request ends in one `http.request` log line, the service's access log (uvicorn's own is off). With
OPS_REQUEST_TIMING on the response also carries Server-Timing (`app` and `db`), which the browser's network panel
shows. Field names follow OpenTelemetry's HTTP conventions so a later exporter can send the same data.

Database time and query count come from the engine listeners `ops_store.open_database` installs, added to the
`RequestTiming` of the request whose task ran the query. `db.query_count` is the route's own statements; the isolation
layer's statements that enter and leave a transaction's scope or role, whose number differs by database, are timed
with them and counted apart (`db.isolation_query_count`). Work outside a request (workers, the engine poller) has no
`RequestTiming`, so its queries are never counted to one. The same listeners count the request's transactions
(`db.tx_count`, one for a route on the request transaction), the longest any of them stayed open (`db.tx_open_ms`) and
what the pool cost it: the connections it checked out (`db.connection_count`, one for a route on the request
transaction), the time spent waiting for them (`db.pool.wait_ms`) and the most connections in use at one of its
checkouts against the pool's limit (`db.pool.in_use`, `db.pool.limit`). `ServiceClient` adds each call to another
service (`http.client.call_count`) and the calls made while one of the request's transactions was open
(`http.client.calls_in_tx`), which hold that transaction for as long as the other service takes.
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
    db_isolation_queries: int = 0
    # The verified caller's tenant and team (note_caller), for the request's log line.
    tenant_id: str | None = None
    team_id: str | None = None

    db_tx: int = 0
    # The longest one transaction of the request stayed open, BEGIN to COMMIT or ROLLBACK.
    db_tx_open_ms: float = 0.0
    # The request's transactions open now: begun and not yet committed or rolled back.
    db_tx_open: int = 0
    db_connections: int = 0
    service_calls: int = 0
    service_calls_in_tx: int = 0
    pool_wait_ms: float = 0.0
    pool_in_use: int = 0
    pool_limit: int | None = None

    def add_query(self, ms: float, *, isolation: bool = False) -> None:
        """`isolation`: a statement the store's isolation layer ran to enter or leave a scope or role, timed with the
        route's but counted apart, since the number differs by database (PostgreSQL one per transaction, SQL Server
        more) and a route's statement budget holds on both."""
        self.db_ms += ms
        if isolation:
            self.db_isolation_queries += 1
        else:
            self.db_queries += 1

    def begin_transaction(self) -> None:
        self.db_tx_open += 1

    def add_transaction(self, open_ms: float) -> None:
        self.db_tx += 1
        self.db_tx_open = max(0, self.db_tx_open - 1)
        self.db_tx_open_ms = max(self.db_tx_open_ms, open_ms)

    def add_service_call(self) -> None:
        self.service_calls += 1
        if self.db_tx_open:
            self.service_calls_in_tx += 1

    def add_checkout(self, wait_ms: float, *, in_use: int, limit: int | None) -> None:
        self.db_connections += 1
        self.pool_wait_ms += wait_ms
        self.pool_in_use = max(self.pool_in_use, in_use)
        self.pool_limit = limit


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
        "db.isolation_query_count": timing.db_isolation_queries,
        "db.tx_count": timing.db_tx,
        "db.tx_open_ms": round(timing.db_tx_open_ms, 1),
        "db.connection_count": timing.db_connections,
        "db.pool.wait_ms": round(timing.pool_wait_ms, 1),
        "db.pool.in_use": timing.pool_in_use,
        "db.pool.limit": timing.pool_limit,
        "http.client.call_count": timing.service_calls,
        "http.client.calls_in_tx": timing.service_calls_in_tx,
        "tenant_id": timing.tenant_id,
        "team_id": timing.team_id,
    }
    log.info("http.request", **fields)
