"""`make ... ISOLATED=1` acts only on the isolated stack (c-099, tick 14), by failure mode: a run started inside
another make inherits the shared stack's exported addresses and `?=` keeps them, so an isolated reset or migrate
would drop or change the shared database. `make -n` prints what would run without running it."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHARED = "postgresql+asyncpg://ops:ops@localhost:5477/ops_runtime"
# What a make run on the shared stack exports to everything it starts.
SHARED_ENV = {
    "OPS_DATABASE_URL": SHARED,
    "OPS_TEST_DATABASE_URL": "postgresql+asyncpg://ops:ops@localhost:5477/ops_test",
    "OPS_PG_PORT": "5477",
    "OPS_AGENTS_PORT": "8700",
    "OPS_PLATFORM_PORT": "8710",
    "OPS_PLATFORM_URL": "http://127.0.0.1:8710",
    "OPS_STACK": "shared",
}


def dry_run(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("OPS_", "MAKE"))}
    return subprocess.run(
        ["make", "-n", *args], cwd=ROOT, env={**clean, **env}, capture_output=True, text=True, check=False
    )


def test_an_isolated_reset_inside_a_shared_make_never_names_the_shared_database() -> None:
    out = dry_run("reset-db", "ISOLATED=1", "CONFIRM=yes", env=SHARED_ENV)
    text = out.stdout + out.stderr
    assert out.returncode == 0, text
    assert "localhost:5477/" not in text and "localhost:6477/ops_runtime" in text, text


def test_an_isolated_make_up_inside_a_shared_make_never_names_the_shared_database() -> None:
    out = dry_run("up", "ISOLATED=1", env=SHARED_ENV)
    text = out.stdout + out.stderr
    assert "localhost:5477/" not in text and "localhost:6477/ops_runtime" in text, text


def test_an_isolated_reset_of_the_shared_database_is_refused_before_anything_runs() -> None:
    out = dry_run("reset-db", "ISOLATED=1", "CONFIRM=yes", f"OPS_DATABASE_URL={SHARED}", env={})
    assert out.returncode != 0 and "reset-db refused" in out.stderr, out.stdout + out.stderr
    assert "stop-for-reset" not in out.stdout, out.stdout
