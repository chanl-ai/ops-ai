"""check_downgrades.py --all, by failure mode: a migration with an empty downgrade() reached main because the check ran
only at pre-commit on staged files; a waiting-list entry whose downgrade was since written stayed on the list."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EMPTY = "def upgrade():\n    pass\n\n\ndef downgrade():\n    pass\n"
UNDOES = "def upgrade():\n    pass\n\n\ndef downgrade():\n    op.drop_table('t')\n"
OLD = "services/a-service/migrations/versions/0001_old.py"
NEW = "services/a-service/migrations/versions/0002_new.py"


def run(tmp: Path, files: dict[str, str], waiting: list[str]) -> tuple[int, str]:
    for name, text in files.items():
        (tmp / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp / name).write_text(text)
    (tmp / "waiting.txt").write_text("\n".join(waiting))
    done = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/check_downgrades.py"),
            "--all",
            "--root",
            str(tmp),
            "--waiting",
            "waiting.txt",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode, done.stdout


def test_an_empty_downgrade_off_the_waiting_list_fails(tmp_path: Path) -> None:
    code, out = run(tmp_path, {OLD: EMPTY, NEW: EMPTY}, [OLD])
    assert code == 1 and NEW in out and OLD not in out, out


def test_a_listed_migration_that_now_undoes_its_upgrade_is_taken_off_the_list(tmp_path: Path) -> None:
    code, out = run(tmp_path, {OLD: UNDOES, NEW: UNDOES}, [OLD])
    assert code == 1 and "remove it from" in out and OLD in out, out


def test_the_list_as_it_stands_passes(tmp_path: Path) -> None:
    assert run(tmp_path, {OLD: EMPTY, NEW: UNDOES}, [OLD])[0] == 0
