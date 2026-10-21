"""The connect policy (ops_store.database), by failure mode: an attempt that stalls fails the caller although a second
would connect, a stall that never clears retries forever, an error that cannot clear (bad credentials) is retried,
and asyncpg waits its own default minute instead of the setting. Driven through a real engine's connect, so the hook
on the Engine class is what is tested."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from asyncpg.transaction import Transaction  # pyright: ignore[reportMissingTypeStubs]

from ops_service_kit.settings import Settings
from ops_store.database import connect, connect_policy, open_database


class Flaky:
    """Stands in for a dialect's connect: the first `stalls` calls time out, then the real connect runs."""

    def __init__(self, real: Any, stalls: int, error: BaseException | None = None) -> None:
        self.real, self.stalls, self.error, self.calls = real, stalls, error or TimeoutError(), 0

    def __call__(self, *cargs: Any, **cparams: Any) -> Any:
        self.calls += 1
        if self.calls <= self.stalls:
            raise self.error
        return self.real(*cargs, **cparams)


def _engine(
    monkeypatch: pytest.MonkeyPatch, stalls: int, error: BaseException | None = None
) -> tuple[sa.Engine, Flaky]:
    engine = sa.create_engine("sqlite://")
    flaky = Flaky(engine.dialect.connect, stalls, error)
    monkeypatch.setattr(engine.dialect, "connect", flaky)
    return engine, flaky


def test_a_stalled_attempt_is_made_again_and_the_connection_opens(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, flaky = _engine(monkeypatch, stalls=connect_policy()[1] - 1)
    with engine.connect() as c:
        assert c.execute(sa.text("select 1")).scalar_one() == 1
    assert flaky.calls == connect_policy()[1]


def test_a_stall_that_never_clears_fails_after_the_last_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, flaky = _engine(monkeypatch, stalls=100)
    with pytest.raises(TimeoutError):
        engine.connect()
    assert flaky.calls == connect_policy()[1]


def test_an_error_that_cannot_clear_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    engine, flaky = _engine(monkeypatch, stalls=100, error=PermissionError("password authentication failed"))
    with pytest.raises(PermissionError):
        engine.connect()
    assert flaky.calls == 1


def test_asyncpg_is_given_the_setting_s_timeout() -> None:
    seen: dict[str, Any] = {}

    class Dialect:
        driver = "asyncpg"

        def connect(self, *_cargs: Any, **cparams: Any) -> str:
            seen.update(cparams)
            return "conn"

    assert connect(Dialect(), [], {"host": "h"}, timeout_s=12.5, attempts=2) == "conn"  # pyright: ignore[reportArgumentType]
    assert seen == {"host": "h", "timeout": 12.5}


class Pings:
    """Stands in for the dialect's ping and counts it; `dead` makes the next one fail, as on a closed connection."""

    def __init__(self) -> None:
        self.calls, self.dead = 0, False

    def __call__(self, _dbapi_connection: Any) -> bool:
        self.calls += 1
        if self.dead:
            self.dead = False
            raise ConnectionResetError("closed while pooled")
        return True


async def _two_checkouts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, dead: bool = False) -> Pings:
    """Two transactions on one pooled connection; with `dead`, the connection is closed between them."""
    db = open_database(f"sqlite+aiosqlite:///{tmp_path / 'pooled.db'}")
    pings = Pings()
    monkeypatch.setattr(db.dialect, "do_ping", pings)
    try:
        async with db.connect() as c:
            await c.execute(sa.text("SELECT 1"))
        pings.dead = dead
        async with db.connect() as c:
            assert (await c.execute(sa.text("SELECT 1"))).scalar() == 1
    finally:
        await db.dispose()
    return pings


async def test_a_reused_connection_is_tested_and_a_new_one_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (await _two_checkouts(tmp_path, monkeypatch)).calls == 1


async def test_a_connection_closed_while_pooled_is_replaced_and_the_transaction_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (await _two_checkouts(tmp_path, monkeypatch, dead=True)).calls == 1


async def test_on_postgresql_the_test_is_one_statement_with_no_transaction(monkeypatch: pytest.MonkeyPatch) -> None:
    """pool_pre_ping opened and rolled back a transaction around its ping: three round trips per checkout (c-451)."""
    url = Settings().database_url
    if not url.startswith("postgresql"):
        pytest.skip("the asyncpg test needs PostgreSQL")
    began: list[int] = []
    real: Any = Transaction.start

    async def counted(self: Any) -> None:
        began.append(1)
        await real(self)

    db = open_database(url)
    try:
        async with db.connect() as c:
            await c.execute(sa.text("SELECT 1"))
            await c.rollback()
        monkeypatch.setattr(Transaction, "start", counted)
        async with db.connect():
            pass
    finally:
        await db.dispose()
    assert began == []
