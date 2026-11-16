"""Opening a service's database, and how every engine in a process that imports ops_store opens a connection.

  db = open_database(settings.database_url)   # the handle code outside a store holds; never AsyncEngine itself
  await reachable(db)                         # /health's probe: True, or False within database_health_timeout_s

The pool is a setting, not the library's default: OPS_DB__SIZE connections kept, OPS_DB__OVERFLOW more under load,
and OPS_DB__WAIT_S for a request to wait for one (`Settings.db`).

A pooled connection is tested before it is handed out, and replaced when the database or a proxy closed it while it
sat in the pool. On asyncpg the test is one round trip; SQLAlchemy's pool_pre_ping wraps it in BEGIN and ROLLBACK (for
pgbouncer's transaction mode, which no install uses), three round trips on every transaction. Each connect
attempt is bounded by `database_connect_timeout_s`, and a stalled or reset attempt is made again, up to
`database_connect_attempts`.

On a host running several builders' suites and Docker, an asyncpg connect has waited a full minute for the server's
reply to its first message and failed a test that had nothing to do with the database (three QA reds on 2026-10-19).
A second attempt connects at once, so a bounded retry turns the stall into a short delay. The hook is installed on the
Engine class, so engines made anywhere (services, tests, scripts) get it without passing anything.
"""

from __future__ import annotations

import asyncio
import time
import weakref
from functools import cache
from typing import Any

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DisconnectionError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool, ConnectionPoolEntry, NullPool
from sqlalchemy.util import await_

from ops_service_kit.logging import get_logger
from ops_service_kit.request_timing import RequestTiming
from ops_service_kit.request_timing import current as current_request
from ops_service_kit.settings import PoolSettings, Settings

log = get_logger(__name__)
# The handle routes, workers and entry points hold. It is the engine today; code outside a store only passes it to a
# store, so a pool or driver change stays inside ops_store and the stores.
Database = AsyncEngine


# Set on a pooled connection once it has been used: a connection made for this checkout needs no test.
_CHECKED_IN = "ops_checked_in"
# The start of each statement running on a connection, for the request timing.
_STARTED = "ops_statement_started"
# The request a connection's open transaction belongs to and when it began.
_TX = "ops_transaction"


class _TimedPool(AsyncAdaptedQueuePool):
    """The queue pool, telling the request how long it waited for each connection and how full the pool was."""

    def _do_get(self) -> ConnectionPoolEntry:
        begun = time.perf_counter()
        try:
            return super()._do_get()
        finally:
            request = current_request()
            if request is not None:
                over = self._max_overflow  # pyright: ignore[reportPrivateUsage]
                request.add_checkout(
                    (time.perf_counter() - begun) * 1000,
                    in_use=self.checkedout(),
                    limit=None if over < 0 else self.size() + over,
                )


def open_database(url: str, *, pool: PoolSettings | None = None, **options: Any) -> Database:
    """The service's database handle: every checkout of a pooled connection tests it first, and
    connects through the policy below. `pool` is the process's `Settings.db` unless one is passed; an engine option
    given by name (the checkpointer's own pool size) wins over it."""
    if make_url(url).get_backend_name() != "sqlite":
        pool = pool or Settings().db
        options.setdefault("poolclass", _TimedPool)
        options.setdefault("pool_size", pool.size)
        options.setdefault("max_overflow", pool.overflow)
        options.setdefault("pool_timeout", pool.wait_s)
    engine = create_async_engine(url, **options)
    dialect = engine.dialect

    def checked_in(_dbapi_connection: Any, record: Any) -> None:
        record.info[_CHECKED_IN] = True

    def test_before_use(dbapi_connection: Any, record: Any, _proxy: Any) -> None:
        if not record.info.get(_CHECKED_IN):
            return  # connected just now
        driver = getattr(dbapi_connection, "driver_connection", None)
        try:
            if dialect.driver == "asyncpg" and driver is not None:
                await_(driver.fetchrow(";"))
            else:
                dialect.do_ping(dbapi_connection)
        except Exception as e:
            # The pool discards this connection and checks out another (SQLAlchemy's pessimistic disconnect handling).
            raise DisconnectionError(str(e)) from e

    event.listen(engine.sync_engine, "checkin", checked_in)
    event.listen(engine.sync_engine, "checkout", test_before_use)
    event.listen(engine.sync_engine, "before_cursor_execute", _statement_started)
    event.listen(engine.sync_engine, "after_cursor_execute", _statement_finished)
    event.listen(engine.sync_engine, "begin", _transaction_began)
    event.listen(engine.sync_engine, "commit", _transaction_ended)
    event.listen(engine.sync_engine, "rollback", _transaction_ended)
    return engine


def _statement_started(conn: sa.Connection, *_: Any) -> None:
    conn.info.setdefault(_STARTED, []).append(time.perf_counter())


def _statement_finished(conn: sa.Connection, *_: Any) -> None:
    started = conn.info.get(_STARTED)
    if not started:
        return
    begun = started.pop()
    # Counted to the request whose task ran the statement; a worker or poller statement has no request.
    request = current_request()
    if request is not None:
        request.add_query((time.perf_counter() - begun) * 1000)


def _transaction_began(conn: sa.Connection) -> None:
    # Counted to the request whose task began it, so a transaction a stream's generator opens later still counts.
    request = current_request()
    if request is not None:
        request.begin_transaction()
        conn.info[_TX] = (request, time.perf_counter())


def _transaction_ended(conn: sa.Connection) -> None:
    if conn.invalidated:
        # A statement cancelled mid-flight invalidates the connection, and reading its info then raises
        # PendingRollbackError in place of the cancellation; the transaction goes uncounted.
        return
    found: tuple[RequestTiming, float] | None = conn.info.pop(_TX, None)
    if found is not None:
        request, begun = found
        request.add_transaction((time.perf_counter() - begun) * 1000)


# The engines whose last probe failed, so an outage is logged when it starts and not on every poll.
_DOWN: weakref.WeakSet[sa.Engine] = weakref.WeakSet()


# Per database, an engine with no pool for /health's probe: a pool every request holds would make a busy service
# answer degraded while its database is healthy.
_PROBES: weakref.WeakKeyDictionary[sa.Engine, AsyncEngine] = weakref.WeakKeyDictionary()


def _probe_engine(db: Database) -> AsyncEngine:
    found = _PROBES.get(db.sync_engine)
    if found is None:
        found = _PROBES[db.sync_engine] = create_async_engine(db.url, poolclass=NullPool)
    return found


async def reachable(db: Database, *, timeout_s: float | None = None) -> bool:
    """Whether the database answers one statement that names no table, within `timeout_s` (the setting
    `database_health_timeout_s` by default) from the connect to the reply: what a service's /health asks. Needs no
    caller, so it is a connection of its own, opened outside the pool and closed after; this package's one probe
    (tests/test_isolation_sites.py, OWNED)."""
    limit = timeout_s if timeout_s is not None else Settings().database_health_timeout_s
    try:
        async with asyncio.timeout(limit):
            async with _probe_engine(db).connect() as c:
                await c.execute(sa.select(1))
    except Exception as e:
        if db.sync_engine not in _DOWN:
            _DOWN.add(db.sync_engine)
            log.warning("database_unreachable", error=f"{type(e).__name__}: {e}"[:500], timeout_s=limit)
        return False
    _DOWN.discard(db.sync_engine)
    return True


# An attempt that stalled or was cut off; refused credentials or a missing database fail at once, every time.
RETRIED = (TimeoutError, ConnectionResetError, ConnectionAbortedError, BrokenPipeError)


@cache
def connect_policy() -> tuple[float, int]:
    s = Settings()
    return s.database_connect_timeout_s, max(1, s.database_connect_attempts)


def connect(dialect: sa.Dialect, cargs: Any, cparams: dict[str, Any], *, timeout_s: float, attempts: int) -> Any:
    """Opens one DBAPI connection, retrying an attempt that stalled or was cut off."""
    if dialect.driver == "asyncpg":
        cparams.setdefault("timeout", timeout_s)
    for attempt in range(1, attempts + 1):
        try:
            return dialect.connect(*cargs, **cparams)
        except RETRIED as e:
            if attempt == attempts:
                raise
            log.warning("database connect retried", attempt=attempt, attempts=attempts, error=type(e).__name__)
    raise AssertionError("unreachable")


@event.listens_for(sa.Engine, "do_connect")
def _do_connect(dialect: sa.Dialect, _record: Any, cargs: Any, cparams: dict[str, Any]) -> Any:
    timeout_s, attempts = connect_policy()
    return connect(dialect, cargs, cparams, timeout_s=timeout_s, attempts=attempts)
