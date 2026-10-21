"""ops_store.isolation (c-409), by failure mode: a transaction that does not carry the caller's tenant, team and scope;
a setting that outlives its transaction (SQL Server keeps session context on the pooled connection); a statement with
no context that reads anyway; a widening that names no reason or leaves no log line; a widening that loses the caller's
tenant. The live cases run on the PostgreSQL conformance database; SQL Server's statements are checked as sent, and run
live in c-419."""

from __future__ import annotations

import contextvars
import logging
from collections.abc import AsyncIterator
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mssql
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.settings import Settings
from ops_store import isolation
from ops_store.backends import backends
from ops_store.conformance import engine_for
from ops_store.team_scope import acting_team

SETTINGS = ("app.tenant_id", "app.team_id", "app.scope")
READ = sa.select(*(sa.func.current_setting(s, True) for s in SETTINGS))


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    (b,) = backends(Settings().database_url)
    e = await engine_for(b)
    yield e
    await e.dispose()


async def test_a_team_transaction_carries_tenant_team_and_scope(engine: AsyncEngine) -> None:
    with isolation.scope("tenant-a", "team-a"):
        async with isolation.isolated_tx(engine) as c:
            assert tuple((await c.execute(READ)).one()) == ("tenant-a", "team-a", "team")


async def test_a_tenant_wide_transaction_carries_no_team(engine: AsyncEngine) -> None:
    with isolation.tenant_wide("test", tenant_id="tenant-a"):
        async with isolation.isolated_tx(engine) as c:
            assert tuple((await c.execute(READ)).one()) == ("tenant-a", "", "tenant")


async def test_the_settings_end_with_the_transaction_even_on_error(engine: AsyncEngine) -> None:
    with isolation.scope("tenant-a", "team-a"), pytest.raises(RuntimeError):
        async with isolation.isolated_tx(engine):
            raise RuntimeError("boom")
    async with engine.connect() as c:
        assert all(v in (None, "") for v in (await c.execute(READ)).one())


async def test_no_context_raises_before_any_statement(engine: AsyncEngine) -> None:
    with pytest.raises(isolation.NoTenantError):
        isolation.tenant()
    with pytest.raises(isolation.NoTenantError):
        async with isolation.isolated_tx(engine):
            pytest.fail("a transaction opened with no tenant")


class _Recorder:
    """A connection stand-in that records the statements a SQL Server transaction sends."""

    dialect = mssql.dialect()

    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, stmt: Any, params: dict[str, Any] | None = None) -> None:
        self.sent.append((str(stmt), dict(params or {})))


async def test_sql_server_sets_and_clears_all_three_keys() -> None:
    conn = _Recorder()
    with isolation.scope("tenant-a", "team-a"):
        await isolation.enter_transaction(conn, isolation.current())  # pyright: ignore[reportArgumentType]
    await isolation.leave_transaction(conn)  # pyright: ignore[reportArgumentType]
    sets = [(p["k"], p["v"]) for s, p in conn.sent if "sp_set_session_context" in s]
    assert sets == [
        ("tenant_id", "tenant-a"),
        ("team_id", "team-a"),
        ("scope", "team"),
        ("tenant_id", None),
        ("team_id", None),
        ("scope", None),
    ]


def _widened(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str]]:
    return [(r.levelno, r.getMessage()) for r in caplog.records if r.getMessage().startswith("isolation.widen")]


def test_a_widening_names_its_reason_and_logs_it(caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(ValueError, match="reason"), isolation.tenant_wide("  ", tenant_id="tenant-a"):
        pass

    def request() -> None:
        isolation.enter("tenant-a", "team-a", kind="person")
        with isolation.tenant_wide("admin_platform_resource"):
            assert isolation.current().scope == "tenant" and acting_team() is None
        assert isolation.current().scope == "team" and acting_team() == "team-a"

    with caplog.at_level(logging.INFO, logger="ops_store.isolation"):
        contextvars.copy_context().run(request)
    ((level, line),) = _widened(caplog)
    assert level == logging.INFO
    assert "reason=admin_platform_resource" in line and "tenant=tenant-a" in line and "caller=person" in line


def test_a_loops_widening_is_logged_below_info(caplog: pytest.LogCaptureFixture) -> None:
    """A relay or claim loop widens on every pass; its line is DEBUG, so INFO keeps the requests' widenings (c-451)."""

    def loop() -> None:
        with isolation.tenant_wide("outbox_relay", tenant_id="tenant-a"):
            pass

    with caplog.at_level(logging.DEBUG, logger="ops_store.isolation"):
        contextvars.Context().run(loop)
    ((level, line),) = _widened(caplog)
    assert level == logging.DEBUG and "reason=outbox_relay" in line and "caller=task" in line


def test_a_widening_with_no_tenant_named_keeps_the_callers_tenant() -> None:
    def request() -> None:
        isolation.enter("tenant-a", "team-a", kind="person")
        with isolation.tenant_wide("test") as wide:
            assert (wide.tenant_id, wide.team_id, wide.scope, wide.kind) == ("tenant-a", None, "tenant", "person")
        assert isolation.current().team_id == "team-a"

    contextvars.copy_context().run(request)
    with pytest.raises(isolation.NoTenantError), isolation.tenant_wide("test"):
        pytest.fail("widened with no tenant")


async def test_a_system_transaction_needs_a_reason(engine: AsyncEngine, caplog: pytest.LogCaptureFixture) -> None:
    with pytest.raises(ValueError, match="reason"):
        async with isolation.system_tx(engine, ""):
            pass
    with caplog.at_level(logging.DEBUG, logger="ops_store.isolation"):
        async with isolation.system_tx(engine, "claim_work") as c:
            assert (await c.execute(sa.select(1))).scalar_one() == 1
    assert any(level == logging.DEBUG and "reason=claim_work" in line for level, line in _widened(caplog))
