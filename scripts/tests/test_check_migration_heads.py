"""check_migration_heads.py, by failure mode: two migrations that follow the same revision reach main (a second 0120),
and the first to hear of it is the deploy, when Alembic refuses to upgrade a chain with two heads."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = '"""{name}"""\n\nfrom __future__ import annotations\n\nrevision = "{name}"\ndown_revision = {down}\n'


def write(versions: Path, name: str, down: str | None) -> None:
    versions.mkdir(parents=True, exist_ok=True)
    (versions / f"{name}.py").write_text(MIGRATION.format(name=name, down=f'"{down}"' if down else "None"))


def run(versions: Path) -> tuple[int, str]:
    done = subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_migration_heads.py"), str(versions)],
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode, done.stdout


def test_a_second_migration_after_the_same_revision_fails_and_names_both_heads(tmp_path: Path) -> None:
    versions = tmp_path / "services/a-service/migrations/versions"
    write(versions, "0001_first", None)
    write(versions, "0002_runs", "0001_first")
    assert run(versions)[0] == 0, "a chain with one head passes"
    write(versions, "0002_claims", "0001_first")
    code, out = run(versions)
    assert code == 1 and "0002_runs" in out and "0002_claims" in out, out
