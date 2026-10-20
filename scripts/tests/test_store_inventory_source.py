"""The store inventory check reads the checkout it runs from, by failure mode: another builder's uncommitted table in
the shared tree failing a commit that does not touch it, and a committed table with no data.md row getting through.
The shared virtualenv's editable installs point at the working tree; here a second copy on PYTHONPATH plays that tree,
so the check must ignore it."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STORE = "services/models-service/src/ops_models/store/tables.py"
PROBE = '\nzz_probe = sa.Table("zz_probe", metadata, sa.Column("id", sa.String(64), primary_key=True))\n'


def _copy(dest: Path, *, probe: bool) -> Path:
    """HEAD's services, packages and data.md, with this tree's inventory script (the one under test)."""
    dest.mkdir()
    archive = subprocess.run(
        ["git", "-C", str(ROOT), "archive", "HEAD", "--", "services", "packages", "docs/architecture/data.md"],
        check=True,
        capture_output=True,
    ).stdout
    subprocess.run(["tar", "-x", "-C", str(dest)], input=archive, check=True)
    (dest / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/store_inventory.py", dest / "scripts/store_inventory.py")
    if probe:
        with (dest / STORE).open("a") as f:
            f.write(PROBE)
    return dest


def _check(checkout: Path, tree: Path) -> subprocess.CompletedProcess[str]:
    """The check run from `checkout`, with `tree`'s source ahead of it on the path as the editable installs put it."""
    tree_paths = ":".join(str(p) for p in sorted([*tree.glob("packages/*/src"), *tree.glob("services/*/src")]))
    return subprocess.run(
        [sys.executable, str(checkout / "scripts/store_inventory.py"), "--check"],
        env={"PYTHONPATH": tree_paths, "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def copies(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    base = tmp_path_factory.mktemp("inventory")
    return _copy(base / "clean", probe=False), _copy(base / "probe", probe=True)


def test_an_uncommitted_table_elsewhere_does_not_fail_a_commit(copies: tuple[Path, Path]) -> None:
    clean, probe = copies
    r = _check(clean, tree=probe)
    assert r.returncode == 0, r.stderr


def test_a_committed_table_without_its_data_md_row_fails(copies: tuple[Path, Path]) -> None:
    clean, probe = copies
    r = _check(probe, tree=clean)
    assert r.returncode == 1 and "inventory is stale" in r.stderr, r.stderr
