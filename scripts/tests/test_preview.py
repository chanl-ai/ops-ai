"""Preview stacks (scripts/preview.py, make/preview.mk), by failure mode: a fourth stack starts and loads the machine;
a dead preview still counts and blocks a new one; stopping an unknown branch looks like success; the page and the list
disagree; review-main touches :3016 when its worktree is dirty. The stack itself is not started here (--dry-run);
the real start and stop are proven by hand on a branch."""

from __future__ import annotations

import importlib.util
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
        seed(tmp_path, b, 36000 + i * 1000, live=True)
    r = run(tmp_path, "start", "--branch", "feat/d", "--dry-run")
    assert r.returncode == 1
    assert all(b in r.stderr for b in ("feat/a", "feat/b", "feat/c")) and "39016" not in r.stdout
    assert not (tmp_path / "wt").exists()

    seed(tmp_path, "feat/b", 37000, live=False)  # crashed: frees its slot and its offset
    r = run(tmp_path, "start", "--branch", "feat/d", "--dry-run")
    assert r.returncode == 0 and "offset 37000" in r.stdout


def test_same_branch_twice_names_its_url(tmp_path: Path) -> None:
    seed(tmp_path, "feat/a", 36000, live=True)
    r = run(tmp_path, "start", "--branch", "feat/a", "--dry-run")
    assert r.returncode == 1 and "http://localhost:39016" in r.stderr


def test_stop_unknown_branch_changes_nothing_and_list_matches_page(tmp_path: Path) -> None:
    seed(tmp_path, "feat/a", 36000, live=True)
    r = run(tmp_path, "stop", "--branch", "feat/nope")
    assert r.returncode == 1 and "no preview for feat/nope" in r.stderr
    assert (tmp_path / "previews" / "feat_a.json").exists()
    out = run(tmp_path, "list").stdout
    assert "feat/a\thttp://localhost:39016\t2h" in out
    assert 'href="http://localhost:39016"' in (tmp_path / "p.html").read_text()


def test_empty_list_writes_an_empty_page(tmp_path: Path) -> None:
    assert "no previews" in run(tmp_path, "list").stdout
    assert "No previews running." in (tmp_path / "p.html").read_text()


def test_every_port_of_every_preview_slot_stays_below_the_ephemeral_range() -> None:
    """A server bound to port 0 (macOS gives it a port from 49152 up) can hold a preview's port and stop make up."""
    spec = importlib.util.spec_from_file_location("preview", ROOT / "scripts" / "preview.py")
    assert spec and spec.loader
    preview = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preview)

    show = "show:\n\t@$(foreach v,$(filter OPS_%_PORT,$(.VARIABLES)),echo $($(v));)\n"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OPS_", "MAKE", "STACK_"))}
    last = preview.FIRST_OFFSET + (preview.LIMIT - 1) * preview.STEP
    out = subprocess.run(
        ["make", "-s", "--no-print-directory", "-f", "Makefile", "-f", "/dev/stdin", "show", f"OPS_PORT_OFFSET={last}"],
        cwd=ROOT,
        input=show,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    ports = [int(p) for p in out.split() if p.isdigit()]
    assert len(ports) > 10 and max(ports) < preview.EPHEMERAL_FIRST, (last, max(ports))
