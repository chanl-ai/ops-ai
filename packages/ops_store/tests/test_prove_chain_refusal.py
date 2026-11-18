"""prove_chain downgrades the database it is given, so it refuses one that is not a throwaway test database before it
connects or runs anything: a service test that passed Settings' URL started a downgrade on the live stack's database."""

from __future__ import annotations

from typing import Any

import pytest
from alembic import command
from alembic.config import Config

from ops_store import testing
from ops_store.testing import RefusedDatabase, prove_chain

# 10.255.255.1 routes nowhere: a connection attempt would hang or fail with a network error, never RefusedDatabase.
HOST = "postgresql+asyncpg://u:p@10.255.255.1:5432"
TEST = f"{HOST}/ops_test_files"
SCRATCH = "mssql+aioodbc://sa:p@10.255.255.1:1433/ops_files_test_0a1b2c3d"


@pytest.mark.parametrize(
    ("url", "test_url", "env_url"),
    [
        (f"{HOST}/ops_runtime", TEST, f"{HOST}/ops_runtime"),  # the live stack's database
        (f"{HOST}/ops_other", TEST, f"{HOST}/ops_other"),  # not OPS_TEST_DATABASE_URL's
        (TEST, None, TEST),  # OPS_TEST_DATABASE_URL unset (plain pytest)
        (TEST, TEST, f"{HOST}/ops_runtime"),  # env.py would migrate the live database
        ("mssql+aioodbc://sa:p@10.255.255.1:1433/ops_files", TEST, "mssql+aioodbc://sa:p@10.255.255.1:1433/ops_files"),
        (SCRATCH, TEST, None),  # OPS_DATABASE_URL unset: env.py would fall back to Settings' default
    ],
)
def test_a_database_that_is_not_a_throwaway_one_is_refused_before_anything_runs(
    monkeypatch: pytest.MonkeyPatch, url: str, test_url: str | None, env_url: str | None
) -> None:
    for name, value in (("OPS_TEST_DATABASE_URL", test_url), ("OPS_DATABASE_URL", env_url)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    calls: list[str] = []

    def record(name: str) -> Any:
        def call(*_: object, **__: object) -> None:
            calls.append(name)

        return call

    monkeypatch.setattr(command, "upgrade", record("upgrade"))
    monkeypatch.setattr(command, "downgrade", record("downgrade"))
    monkeypatch.setattr(testing, "create_async_engine", record("connect"))
    monkeypatch.setattr(testing, "chain_facts", record("chain_facts"))
    with pytest.raises(RefusedDatabase):
        prove_chain(Config(), "files", url, fresh=SCRATCH)
    assert calls == [], f"ran before refusing: {calls}"
