"""pg_dump through docker reaches a throwaway server on the host's loopback, and a failed dump says why."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from postgres import _run_dump, docker_dump_command  # pyright: ignore[reportPrivateUsage]

URL = "postgresql://postgres:ddl@127.0.0.1:32768/postgres"


def test_linux_shares_the_host_network_for_a_loopback_server() -> None:
    cmd = docker_dump_command(URL, 18, ["--schema-only"], linux=True)
    assert cmd[cmd.index("--network") + 1] == "host"
    assert cmd[-1] == "postgresql://postgres@127.0.0.1:32768/postgres"
    assert "ddl" not in " ".join(cmd)


def test_a_failed_dump_reports_pg_dump_stderr_without_the_password() -> None:
    with pytest.raises(RuntimeError) as e:
        _run_dump([sys.executable, "-c", "import sys; sys.stderr.write('connection refused'); sys.exit(1)", URL])
    assert "connection refused" in str(e.value)
    assert "ddl" not in str(e.value)
