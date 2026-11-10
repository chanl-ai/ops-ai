"""scripts/db-move-image.sh, by failure mode, on two throwaway servers (the old Alpine image and the pgvector one): a
move that loses rows in a table is reported as complete because each database still has its tables; a dump with no
data is restored over the old stack; a restore that fails partway prints its error and carries on; a restore pointed
at a server with data drops its databases."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "db-move-image.sh"
OLD, NEW = "postgres:17-alpine", "pgvector/pgvector:pg17"

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="needs docker for two throwaway servers")


def _server(image: str) -> Generator[str]:
    name = f"ops-move-test-{uuid.uuid4().hex[:8]}"
    env = ["-e", "POSTGRES_USER=ops", "-e", "POSTGRES_PASSWORD=ops", "-e", "POSTGRES_DB=ops_runtime"]
    subprocess.run(["docker", "run", "-d", "--rm", "--name", name, *env, image], check=True, capture_output=True)
    try:
        for _ in range(120):
            ready = subprocess.run(
                ["docker", "exec", name, "psql", "-U", "ops", "-d", "ops_runtime", "-c", "SELECT 1"],
                capture_output=True,
                check=False,
            )
            if ready.returncode == 0:
                break
            time.sleep(0.5)
        else:
            pytest.fail(f"{image} did not start")
        yield name
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


@pytest.fixture
def old() -> Generator[str]:
    yield from _server(OLD)


@pytest.fixture
def new() -> Generator[str]:
    yield from _server(NEW)


def _sql(server: str, database: str, sql: str) -> None:
    subprocess.run(
        ["docker", "exec", "-i", server, "psql", "-U", "ops", "-d", database, "-v", "ON_ERROR_STOP=1"],
        input=sql,
        text=True,
        check=True,
        capture_output=True,
    )


def _move(server: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PG_EXEC": f"docker exec -i {server}"}
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False)


def _seed(server: str) -> None:
    _sql(
        server,
        "ops_runtime",
        "CREATE TABLE cases (id int, note text); INSERT INTO cases SELECT g, 'n' FROM generate_series(1, 30) g;",
    )
    _sql(server, "postgres", "CREATE DATABASE ops_kb;")
    # A table with forced row security, as every tenant table has: the counts must still see each row.
    _sql(
        server,
        "ops_kb",
        "CREATE TABLE kb_bases (tenant_id text, name text); INSERT INTO kb_bases VALUES ('t1', 'a'), ('t2', 'b');"
        " ALTER TABLE kb_bases ENABLE ROW LEVEL SECURITY; ALTER TABLE kb_bases FORCE ROW LEVEL SECURITY;",
    )


def test_a_move_keeps_every_row_and_a_lost_row_is_seen(old: str, new: str, tmp_path: Path) -> None:
    _seed(old)
    before = _move(old, "rows")
    assert before.returncode == 0, before.stderr
    assert "ops_kb public.kb_bases 2" in before.stdout and "ops_runtime public.cases 30" in before.stdout
    counted = tmp_path / "before"
    counted.write_text(before.stdout)
    dump = tmp_path / "dump.sql"
    made = _move(old, "dump", str(dump), str(counted))
    assert made.returncode == 0, made.stderr
    restored = _move(new, "restore", str(dump))
    assert restored.returncode == 0, restored.stderr
    assert _move(new, "rows").stdout == before.stdout
    # The same tables with one row fewer: what a table count reports as a complete move.
    _sql(new, "ops_runtime", "DELETE FROM cases WHERE id = 1;")
    assert _move(new, "rows").stdout != before.stdout


def test_a_dump_short_of_the_rows_counted_is_refused(old: str, tmp_path: Path) -> None:
    _seed(old)
    counted = tmp_path / "before"
    counted.write_text(_move(old, "rows").stdout)
    _sql(old, "ops_runtime", "DELETE FROM cases;")
    refused = _move(old, "dump", str(tmp_path / "dump.sql"), str(counted))
    assert refused.returncode != 0
    assert "the dump holds 2 rows where the server has 32" in refused.stderr


def test_a_server_with_no_rows_is_not_moved(old: str, tmp_path: Path) -> None:
    counted = tmp_path / "before"
    counted.write_text(_move(old, "rows").stdout)
    refused = _move(old, "dump", str(tmp_path / "dump.sql"), str(counted))
    assert refused.returncode != 0
    assert "no rows to move" in refused.stderr


def test_a_restore_stops_at_its_first_error(old: str, new: str, tmp_path: Path) -> None:
    _seed(old)
    counted = tmp_path / "before"
    counted.write_text(_move(old, "rows").stdout)
    dump = tmp_path / "dump.sql"
    assert _move(old, "dump", str(dump), str(counted)).returncode == 0
    text = dump.read_text()
    dump.write_text(text.replace("\\connect ops_kb", "\\connect ops_kb\nSELECT no_such_column FROM nowhere;", 1))
    stopped = _move(new, "restore", str(dump))
    assert stopped.returncode != 0
    assert "nowhere" in stopped.stderr
    assert "kb_bases" not in _move(new, "rows").stdout


def test_a_restore_into_a_server_with_data_is_refused(old: str, tmp_path: Path) -> None:
    _seed(old)
    dump = tmp_path / "dump.sql"
    dump.write_text("SELECT 1;\n")
    refused = _move(old, "restore", str(dump))
    assert refused.returncode != 0
    assert "already holds 32 rows" in refused.stderr
    assert "ops_kb public.kb_bases 2" in _move(old, "rows").stdout
