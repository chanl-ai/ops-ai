"""The suite refuses to start on any PostgreSQL database but the test database, before a migration can run: a bare
`uv run pytest` once migrated the live ops_runtime under every running stack."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ops_service_kit.testdb import refusal

SERVICE = Path(__file__).parents[1]
LIVE = "postgresql+asyncpg://ops:ops@localhost:5477/ops_runtime"
TEST = "postgresql+asyncpg://ops:ops@localhost:5477/ops_test"


def test_a_session_on_the_live_database_stops_before_collecting() -> None:
    env = {**os.environ, "OPS_DATABASE_URL": LIVE, "OPS_TEST_DATABASE_URL": LIVE}
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=SERVICE,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 4, done.stdout + done.stderr
    assert "tests refuse database ops_runtime" in done.stdout + done.stderr


@pytest.mark.parametrize(
    ("url", "test_url", "refused"),
    [
        (TEST, None, "OPS_TEST_DATABASE_URL is unset"),
        (TEST.replace("ops_test", "ops_usecase"), TEST, "not OPS_TEST_DATABASE_URL's"),
        (TEST, TEST, None),
        ("sqlite+aiosqlite://", None, None),
    ],
    ids=["bare-pytest", "another-database", "the-test-database", "sqlite"],
)
def test_only_the_test_database_or_sqlite_is_allowed(url: str, test_url: str | None, refused: str | None) -> None:
    why = refusal(url, test_url)
    assert (why is None) if refused is None else (why is not None and refused in why)
