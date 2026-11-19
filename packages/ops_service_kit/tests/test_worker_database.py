"""A parallel test run's worker database: each worker gets its own copy, and the live-database guard still sees the
pair of URLs make set."""

from __future__ import annotations

import os

import pytest

from ops_service_kit.testdb import refusal, use_worker_database

TEST = "postgresql+asyncpg://ops:ops@localhost:5477/ops_test_r42_ab12cd"
LIVE = "postgresql+asyncpg://ops:ops@localhost:5477/ops_runtime"


def test_a_worker_runs_on_its_own_copy_of_the_test_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")
    monkeypatch.setenv("OPS_TEST_DATABASE_URL", TEST)
    monkeypatch.setenv("OPS_DATABASE_URL", TEST)
    assert use_worker_database() == f"{TEST}_gw3"
    assert os.environ["OPS_DATABASE_URL"] == os.environ["OPS_TEST_DATABASE_URL"] == f"{TEST}_gw3"
    assert refusal(os.environ["OPS_DATABASE_URL"], os.environ["OPS_TEST_DATABASE_URL"]) is None


@pytest.mark.parametrize("test_url", [TEST, LIVE], ids=["live-beside-test", "live-as-both"])
def test_a_worker_pointed_at_the_live_database_is_still_refused(monkeypatch: pytest.MonkeyPatch, test_url: str) -> None:
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")
    monkeypatch.setenv("OPS_TEST_DATABASE_URL", test_url)
    monkeypatch.setenv("OPS_DATABASE_URL", LIVE)
    assert use_worker_database() is None
    assert os.environ["OPS_DATABASE_URL"] == LIVE
    assert refusal(os.environ["OPS_DATABASE_URL"], os.environ["OPS_TEST_DATABASE_URL"]) is not None
