"""Preview stacks (scripts/preview.py, make/preview.mk), by failure mode: a fourth stack starts and loads the machine;
a dead preview still counts and blocks a new one; stopping an unknown branch looks like success; the page and the list
disagree; review-main touches :3016 when its worktree is dirty. The stack itself is not started here (--dry-run);
the real start and stop are proven by hand on a branch."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREVIEW = [sys.executable, str(ROOT / "scripts" / "preview.py")]


def seed(run_root: Path, branch: str, offset: int, live: bool) -> None:
    (run_root / "previews").mkdir(parents=True, exist_ok=True)
    (run_root / "previews" / f"{branch.replace('/', '_')}.json").write_text(
        json.dumps({"branch": branch, "offset": offset, "dir": "/x", "started": time.time() - 7200, "starter": 0})
    )
    d = run_root / f"offset-{offset}"
    d.mkdir(exist_ok=True)
    # Our own pid is alive; an absurd one is not.
    (d / "console.pid").write_text(str(os.getpid() if live else 2**22 + 12345))


def run(tmp: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            *PREVIEW,
            *args,
            "--run-root",
            str(tmp),
            "--page",
            str(tmp / "p.html"),
            "--home",
            str(tmp),
            "--worktrees",
            str(tmp / "wt"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def test_fourth_stack_refused_naming_the_three_and_dead_one_does_not_count(tmp_path: Path) -> None:
    for i, b in enumerate(["feat/a", "feat/b", "feat/c"]):
        seed(tmp_path, b, 51000 + i * 1000, live=True)
    r = run(tmp_path, "start", "--branch", "feat/d", "--dry-run")
    assert r.returncode == 1
    assert all(b in r.stderr for b in ("feat/a", "feat/b", "feat/c")) and "54016" not in r.stdout
    assert not (tmp_path / "wt").exists()

    seed(tmp_path, "feat/b", 52000, live=False)  # crashed: frees its slot and its offset
    r = run(tmp_path, "start", "--branch", "feat/d", "--dry-run")
    assert r.returncode == 0 and "offset 52000" in r.stdout


def test_same_branch_twice_names_its_url(tmp_path: Path) -> None:
    seed(tmp_path, "feat/a", 51000, live=True)
    r = run(tmp_path, "start", "--branch", "feat/a", "--dry-run")
    assert r.returncode == 1 and "http://localhost:54016" in r.stderr


def test_stop_unknown_branch_changes_nothing_and_list_matches_page(tmp_path: Path) -> None:
    seed(tmp_path, "feat/a", 51000, live=True)
    r = run(tmp_path, "stop", "--branch", "feat/nope")
    assert r.returncode == 1 and "no preview for feat/nope" in r.stderr
    assert (tmp_path / "previews" / "feat_a.json").exists()
    out = run(tmp_path, "list").stdout
    assert "feat/a\thttp://localhost:54016\t2h" in out
    assert 'href="http://localhost:54016"' in (tmp_path / "p.html").read_text()


def test_empty_list_writes_an_empty_page(tmp_path: Path) -> None:
    assert "no previews" in run(tmp_path, "list").stdout
    assert "No previews running." in (tmp_path / "p.html").read_text()
