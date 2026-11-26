"""Preview stacks (scripts/preview.py, make/preview.mk), by failure mode: a fourth stack starts and loads the machine;
a dead preview still counts and blocks a new one; stopping an unknown branch looks like success; the page and the list
disagree; review-main touches :3016 when its worktree is dirty. The stack itself is not started here (--dry-run);
the real start and stop are proven by hand on a branch."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
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


def host_env() -> dict[str, str]:
    """The environment without the stack's ports. CI runs these tests under make, which exports OPS_*_PORT; a port in
    the environment beats the offset's value, so the guard would check offset 0's ports and see no clash."""
    drop = ("OPS_", "STACK_HOME", "MAKEFLAGS", "MFLAGS")
    return {k: v for k, v in os.environ.items() if not k.startswith(drop)}


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
    return {**host_env(), "PATH": f"{bin_dir}:{os.environ['PATH']}"}


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
    assert len(ports) > 10 and max(ports) <= preview.MAX_PORT, (last, max(ports))


def test_offset_whose_non_console_port_is_held_is_skipped_naming_the_holder(tmp_path: Path) -> None:
    # 44750 is offset 36000's files port; the console port 39016 is free, which is all the old check looked at.
    env = fake_lsof(tmp_path, [(777, "codeloop-hub", 44750)])
    r = run(tmp_path, "start", "--branch", "feat/a", "--dry-run", env=env)
    assert r.returncode == 0 and "offset 37000" in r.stdout


def test_offset_over_the_port_range_is_refused(tmp_path: Path) -> None:
    r = run(tmp_path, "check-offset", "--offset", "41000")
    assert r.returncode == 1 and "49151" in r.stderr


def test_another_branchs_data_blocks_the_offset_and_the_same_branchs_does_not(tmp_path: Path) -> None:
    (tmp_path / "data" / "offset-36000").mkdir(parents=True)
    (tmp_path / "data" / "offset-36000" / "branch").write_text("feat/other")
    assert "offset 37000" in run(tmp_path, "start", "--branch", "feat/a", "--dry-run").stdout
    (tmp_path / "data" / "offset-36000" / "branch").write_text("feat/a")
    assert "offset 36000" in run(tmp_path, "start", "--branch", "feat/a", "--dry-run").stdout


def test_hand_start_refused_on_a_foreign_listener_but_not_on_its_own_stack(tmp_path: Path) -> None:
    env = fake_lsof(tmp_path, [(4242, "node", 44750)])
    r = run(tmp_path, "check-offset", "--offset", "36000", env=env)
    assert r.returncode == 1 and "44750" in r.stderr
    (tmp_path / "offset-36000").mkdir()
    (tmp_path / "offset-36000" / "files.pid").write_text("4242")
    assert run(tmp_path, "check-offset", "--offset", "36000", env=env).returncode == 0


def test_no_usable_offset_refuses_in_one_line_naming_pid_and_command(tmp_path: Path) -> None:
    env = fake_lsof(tmp_path, [(900 + i, f"holder{i}", 3016 + 36000 + i * 1000) for i in range(10)])
    r = run(tmp_path, "start", "--branch", "feat/a", "--dry-run", env=env)
    assert r.returncode == 1 and len(r.stderr.strip().splitlines()) == 1
    assert "pid 900 holder0" in r.stderr and "pid 903 holder3" in r.stderr


def test_unmarked_data_of_a_registered_preview_is_claimed_by_its_branch(tmp_path: Path) -> None:
    seed(tmp_path, "feat/a", 36000, live=False)  # a preview started before markers existed
    (tmp_path / "data" / "offset-36000").mkdir(parents=True)
    (tmp_path / "data" / "offset-37000").mkdir(parents=True)  # nobody's
    r = run(tmp_path, "start", "--branch", "feat/a", "--dry-run")
    assert "offset 36000" in r.stdout
    assert (tmp_path / "data" / "offset-36000" / "branch").read_text() == "feat/a"
    r = run(tmp_path, "start", "--branch", "feat/b", "--dry-run")
    assert "offset 38000" in r.stdout and "offset 37000" not in r.stdout


def test_make_up_in_its_own_worktree_claims_an_unmarked_folder_and_refuses_another_branchs(tmp_path: Path) -> None:
    d = tmp_path / "data" / "offset-37000"
    d.mkdir(parents=True)
    assert run(tmp_path, "check-offset", "--offset", "37000", "--branch", "feat/x").returncode == 0
    assert (d / "branch").read_text() == "feat/x"
    r = run(tmp_path, "check-offset", "--offset", "37000", "--branch", "feat/y")
    assert r.returncode == 1 and "belongs to feat/x" in r.stderr


def test_listener_that_is_a_child_of_the_stacks_pidfile_pid_is_its_own(tmp_path: Path) -> None:
    env = fake_lsof(tmp_path, [(98500, "next-server", 41016)])
    (tmp_path / "bin" / "ps").write_text("#!/bin/sh\necho '98360 1'\necho '98500 98360'\n")
    (tmp_path / "bin" / "ps").chmod(0o755)
    (tmp_path / "offset-38000").mkdir()
    (tmp_path / "offset-38000" / "console.pid").write_text("98360")
    assert run(tmp_path, "check-offset", "--offset", "38000", env=env).returncode == 0
    (tmp_path / "offset-38000" / "console.pid").write_text("555")
    assert run(tmp_path, "check-offset", "--offset", "38000", env=env).returncode == 1


def test_missing_lsof_and_docker_warn_and_the_rest_of_the_check_runs(tmp_path: Path) -> None:
    bin_dir = tmp_path / "nobin"
    bin_dir.mkdir()
    for tool in ("make", "sed", "sh", "git", "od", "tr", "rm", "cat", "uname", "ps"):
        if shutil.which(tool):
            (bin_dir / tool).symlink_to(shutil.which(tool))
    env = {**host_env(), "PATH": str(bin_dir)}
    r = run(tmp_path, "check-offset", "--offset", "41000", env=env)
    assert "lsof not found" in r.stderr and "docker not found" in r.stderr and "49151" in r.stderr
    assert "Traceback" not in r.stderr


def test_a_shared_stack_is_not_blocked_by_the_containers_it_reuses() -> None:
    """The default stack's postgres and OPA hold their base ports; a shared offset stack must not count them."""
    spec = importlib.util.spec_from_file_location("preview", ROOT / "scripts" / "preview.py")
    assert spec and spec.loader
    preview = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preview)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OPS_", "MAKE", "STACK_"))}
    shared = preview.ports_for(400, {**env, "OPS_INFRA": "shared"})
    assert {5477, 8181, 3025, 1025}.isdisjoint(shared), sorted(shared)
    assert 5477 + 400 in preview.ports_for(400, env)
