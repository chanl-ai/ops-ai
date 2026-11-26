"""A dry run reads and plans; it never works in a checkout. A reviewer's dry run inside the main checkout deleted its
.env, so the check refuses any directory inside a path `git worktree list` names and passes a `git archive` export."""

from __future__ import annotations

import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "in_export_only.py"


def run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True, text=True, check=False)


def test_a_worktree_is_refused_and_an_archive_export_passes(tmp_path: Path) -> None:
    refused = run(cwd=ROOT)
    assert refused.returncode == 1 and "git archive" in refused.stderr, refused.stderr
    assert run(str(ROOT / "scripts"), cwd=tmp_path).returncode == 1, "a folder inside a worktree is refused too"
    export = tmp_path / "export"
    export.mkdir()
    archive = subprocess.run(["git", "-C", str(ROOT), "archive", "HEAD", "Makefile"], capture_output=True, check=True)
    tar = tmp_path / "x.tar"
    tar.write_bytes(archive.stdout)
    with tarfile.open(tar) as t:
        t.extractall(export, filter="data")
    ok = run(cwd=export)
    assert ok.returncode == 0, ok.stderr
