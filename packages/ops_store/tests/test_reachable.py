"""`database.reachable(engine)`, the probe every service's /health asks, by failure mode: a probe that needs a caller or
a table, one that raises instead of answering False when the database refuses the connection, one that waits out the
connect policy (three attempts of 30 s) on a server that accepts and never replies, and one that logs every poll of
an outage instead of its start."""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.settings import Settings
from ops_store.backends import backends
from ops_store.conformance import engine_for, sql_server_database
from ops_store.database import open_database, reachable

SQL_SERVER = (os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD"))


@pytest.fixture(params=["postgresql", "mssql"])
async def engine(request: pytest.FixtureRequest) -> AsyncIterator[AsyncEngine]:
    with sql_server_database("ops_reach", *SQL_SERVER) as mssql:
        if request.param == "mssql":
            if mssql is None:
                pytest.skip("set OPS_MSSQL_SERVER and MSSQL_SA_PASSWORD to run on SQL Server")
            url = mssql
        else:
            (backend,) = backends(Settings().database_url)
            await (await engine_for(backend)).dispose()
            url = backend.url
        e = open_database(url)
        yield e
        await e.dispose()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _down_lines(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    msgs: list[object] = [r.msg for r in caplog.records]
    fields = [cast(dict[str, Any], m) for m in msgs if isinstance(m, dict)]
    return [f for f in fields if f.get("event") == "database_unreachable"]


async def test_a_database_that_answers_is_reachable_with_no_caller(engine: AsyncEngine) -> None:
    assert await reachable(engine) is True


async def test_a_refused_connection_is_unreachable_and_logged_once_per_outage(caplog: pytest.LogCaptureFixture) -> None:
    db = open_database(f"postgresql+asyncpg://ops:ops@127.0.0.1:{_free_port()}/none")
    try:
        with caplog.at_level(logging.WARNING, logger="ops_store.database"):
            assert [await reachable(db), await reachable(db)] == [False, False]
    finally:
        await db.dispose()
    (line,) = _down_lines(caplog)
    assert line["error"].startswith(("ConnectionRefusedError", "OSError")), line


async def test_a_server_that_never_replies_is_unreachable_within_the_timeout() -> None:
    silent = await asyncio.start_server(lambda _r, _w: None, "127.0.0.1", 0)
    port = silent.sockets[0].getsockname()[1]
    db = open_database(f"postgresql+asyncpg://ops:ops@127.0.0.1:{port}/none")
    try:
        began = time.monotonic()
        assert await reachable(db, timeout_s=0.3) is False
        assert time.monotonic() - began < 2.0
    finally:
        silent.close()
        await db.dispose()
