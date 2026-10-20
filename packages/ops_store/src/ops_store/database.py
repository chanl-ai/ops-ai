"""Opening a service's database, and how every engine in a process that imports ops_store opens a connection.

  db = open_database(settings.database_url)   # the handle code outside a store holds; never AsyncEngine itself

A connection that the database or a proxy closed while it sat in the pool is replaced on checkout (pool_pre_ping).
Each connect attempt is bounded by `database_connect_timeout_s`, and a stalled or reset attempt is made again, up to
`database_connect_attempts`.

On a host running several builders' suites and Docker, an asyncpg connect has waited a full minute for the server's
reply to its first message and failed a test that had nothing to do with the database (three QA reds on 2026-10-19).
A second attempt connects at once, so a bounded retry turns the stall into a short delay. The hook is installed on the
Engine class, so engines made anywhere (services, tests, scripts) get it without passing anything.
"""

from __future__ import annotations

from functools import cache
from typing import Any

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_service_kit.logging import get_logger
from ops_service_kit.settings import Settings

log = get_logger(__name__)
# The handle routes, workers and entry points hold. It is the engine today; code outside a store only passes it to a
# store, so a pool or driver change stays inside ops_store and the stores (c-346).
Database = AsyncEngine


def open_database(url: str, **options: Any) -> Database:
    """The service's database handle: every checkout tests its connection first, and connects through the policy
    below."""
    return create_async_engine(url, pool_pre_ping=True, **options)


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
