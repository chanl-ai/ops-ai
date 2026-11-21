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


def fake_lsof(tmp: Path, listeners: list[tuple[int, str, int]]) -> dict[str, str]:
    """The machine's listeners, faked at the edge: `lsof -Fpcn` prints what the test says is listening."""
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    (tmp / "listeners").write_text("".join(f"{pid} {cmd} {port}\n" for pid, cmd, port in listeners))
    loop = 'printf "p%s\\nc%s\\nn*:%s\\n" "$pid" "$cmd" "$port"'
    (bin_dir / "lsof").write_text(f"#!/bin/sh\nwhile read pid cmd port; do {loop}; done < {tmp}/listeners\n")
    (bin_dir / "lsof").chmod(0o755)
    (bin_dir / "docker").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "docker").chmod(0o755)
    return {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}


def run(tmp: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            *PREVIEW,
            *args,
            "--data-root",
            str(tmp / "data"),
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
        env=env or fake_lsof(tmp, []),
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


def test_offset_whose_non_console_port_is_held_is_skipped_naming_the_holder(tmp_path: Path) -> None:
    # 59750 is offset 51000's files port; the console port 54016 is free, which is all the old check looked at.
    env = fake_lsof(tmp_path, [(777, "codeloop-hub", 59750)])
    r = run(tmp_path, "start", "--branch", "feat/a", "--dry-run", env=env)
    assert r.returncode == 0 and "offset 52000" in r.stdout


def test_offset_over_the_port_range_is_refused(tmp_path: Path) -> None:
    r = run(tmp_path, "check-offset", "--offset", "57000")
    assert r.returncode == 1 and "65535" in r.stderr


def test_another_branchs_data_blocks_the_offset_and_the_same_branchs_does_not(tmp_path: Path) -> None:
    (tmp_path / "data" / "offset-51000").mkdir(parents=True)
    (tmp_path / "data" / "offset-51000" / "branch").write_text("feat/other")
    assert "offset 52000" in run(tmp_path, "start", "--branch", "feat/a", "--dry-run").stdout
    (tmp_path / "data" / "offset-51000" / "branch").write_text("feat/a")
    assert "offset 51000" in run(tmp_path, "start", "--branch", "feat/a", "--dry-run").stdout


def test_hand_start_refused_on_a_foreign_listener_but_not_on_its_own_stack(tmp_path: Path) -> None:
    env = fake_lsof(tmp_path, [(4242, "node", 59750)])
    r = run(tmp_path, "check-offset", "--offset", "51000", env=env)
    assert r.returncode == 1 and "59750" in r.stderr
    (tmp_path / "offset-51000").mkdir()
    (tmp_path / "offset-51000" / "files.pid").write_text("4242")
    assert run(tmp_path, "check-offset", "--offset", "51000", env=env).returncode == 0


def test_no_usable_offset_refuses_in_one_line_naming_pid_and_command(tmp_path: Path) -> None:
    env = fake_lsof(tmp_path, [(900 + i, f"holder{i}", 3016 + 51000 + i * 1000) for i in range(10)])
    r = run(tmp_path, "start", "--branch", "feat/a", "--dry-run", env=env)
    assert r.returncode == 1 and len(r.stderr.strip().splitlines()) == 1
    assert "pid 900 holder0" in r.stderr and "pid 903 holder3" in r.stderr
