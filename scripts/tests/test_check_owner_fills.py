"""check_owner_fills.py, by failure mode: a new migration fills rows after `SET LOCAL row_security = off`, which
PostgreSQL refuses for a table owner that is no superuser once FORCE is on, so the upgrade stops half way."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OFF = 'def upgrade():\n    op.execute("SET LOCAL row_security = off")\n'
OLD = "services/a-service/migrations/versions/0001_old.py"
NEW = "services/a-service/migrations/versions/0002_new.py"


def test_a_new_migration_that_switches_row_security_off_fails_and_a_listed_one_passes(tmp_path: Path) -> None:
    for name in (OLD, NEW):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(OFF)
    (tmp_path / "waiting.txt").write_text(OLD)
    script = [sys.executable, str(ROOT / "scripts/check_owner_fills.py"), "--root", str(tmp_path)]
    done = subprocess.run([*script, "--waiting", "waiting.txt"], capture_output=True, text=True, check=False)
    assert done.returncode == 1 and NEW in done.stdout and OLD not in done.stdout, done.stdout
    (tmp_path / NEW).write_text('def upgrade():\n    for s in backfill_ddl(tables, "postgresql", chain="a")[0]: ...\n')
    done = subprocess.run([*script, "--waiting", "waiting.txt"], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout
