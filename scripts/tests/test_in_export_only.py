"""A dry run reads and plans; it never works in a checkout. A reviewer's dry run inside the main checkout deleted its
.env, so the check refuses any directory inside a path `git worktree list` names, a separate clone, and a case-variant
of either, and passes a `git archive` export, also when the script itself is a copy inside that export."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "in_export_only.py"


def run(*args: str, cwd: Path, script: Path = SCRIPT) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(script), *args], cwd=cwd, capture_output=True, text=True, check=False)


def export(tmp: Path) -> Path:
    dest = tmp / "export"
    dest.mkdir()
    (tmp / "x.tar").write_bytes(
        subprocess.run(["git", "-C", str(ROOT), "archive", "HEAD"], capture_output=True, check=True).stdout
    )
    with tarfile.open(tmp / "x.tar") as t:
        t.extractall(dest, filter="data")
    shutil.copy(SCRIPT, dest / "scripts" / "in_export_only.py")  # the script under test, committed or not
    return dest


def test_a_checkout_is_refused_and_an_export_passes_even_with_its_own_copy(tmp_path: Path) -> None:
    refused = run(cwd=ROOT)
    assert refused.returncode == 1 and "git archive" in refused.stderr, refused.stderr
    assert run(str(ROOT / "scripts"), cwd=tmp_path).returncode == 1, "a folder inside a checkout is refused too"
    dest = export(tmp_path)
    assert run(cwd=dest).returncode == 0, "run from the real checkout's script, in an export"
    copy = dest / "scripts" / "in_export_only.py"
    assert run(str(dest), cwd=dest, script=copy).returncode == 2, "a copy in an export cannot tell the checkouts"
    assert run("--repo", str(ROOT), str(dest), cwd=dest, script=copy).returncode == 0
    assert run("--repo", str(ROOT), str(ROOT), cwd=dest, script=copy).returncode == 1


def test_a_case_variant_path_and_a_separate_clone_are_refused(tmp_path: Path) -> None:
    swapped = Path(str(ROOT).swapcase())
    if swapped.exists():  # a case-insensitive file system, as on macOS
        assert run(str(swapped), cwd=tmp_path).returncode == 1
    clone = tmp_path / "clone"
    subprocess.run(["git", "init", "-q", str(clone)], check=True)
    shutil.copy(SCRIPT, clone / "in_export_only.py")
    assert run("--repo", str(ROOT), str(clone), cwd=tmp_path).returncode == 1
