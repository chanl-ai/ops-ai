"""The connect policy (ops_store.database), by failure mode: an attempt that stalls fails the caller although a second
would connect, a stall that never clears retries forever, an error that cannot clear (bad credentials) is retried,
and asyncpg waits its own default minute instead of the setting. Driven through a real engine's connect, so the hook
on the Engine class is what is tested."""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa

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


def test_an_opened_database_tests_a_pooled_connection_before_handing_it_out() -> None:
    db = open_database("sqlite+aiosqlite://")
    assert getattr(db.pool, "_pre_ping")  # noqa: B009 - the pool keeps the option on a private attribute
