"""scripts/at-most.py must not leave its command running or its slot taken when the wrapper or its parent dies."""

from __future__ import annotations

import importlib.util
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "at-most.py"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_for(predicate, seconds: float = 6.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


def _wrapper_args(tmp: Path) -> list[str]:
    child = f"echo $$ > {tmp}/child.pid; exec sleep 300"
    return [sys.executable, str(SCRIPT), "1", "t", "--", "sh", "-c", child]


def _env(tmp: Path) -> dict[str, str]:
    return {**os.environ, "OPS_SLOT_DIR": str(tmp / "slots")}


def _slot_free(tmp: Path) -> bool:
    probe = subprocess.run(
        [sys.executable, str(SCRIPT), "1", "t", "--", "true"],
        env=_env(tmp),
        timeout=4,
        capture_output=True,
        check=False,
    )
    return probe.returncode == 0


def _child_pid(tmp: Path) -> int:
    assert _wait_for(lambda: (tmp / "child.pid").exists() and (tmp / "child.pid").read_text().strip())
    return int((tmp / "child.pid").read_text())


def test_terminated_wrapper_takes_its_child_down_and_frees_the_slot(tmp_path: Path) -> None:
    wrapper = subprocess.Popen(_wrapper_args(tmp_path), env=_env(tmp_path))
    child = _child_pid(tmp_path)
    wrapper.send_signal(signal.SIGTERM)
    wrapper.wait(timeout=8)
    assert _wait_for(lambda: not _alive(child)), "child outlived the wrapper"
    assert _slot_free(tmp_path)


def test_wrapper_whose_parent_dies_takes_its_child_down(tmp_path: Path) -> None:
    args = " ".join(f"'{a}'" for a in _wrapper_args(tmp_path))
    subprocess.run(["sh", "-c", f"{args} >/dev/null 2>&1 &"], env=_env(tmp_path), check=True)
    child = _child_pid(tmp_path)
    assert _wait_for(lambda: not _alive(child)), "child outlived the dead parent"
    assert _slot_free(tmp_path)


def test_slot_recorded_for_a_dead_pid_is_reclaimed(tmp_path: Path) -> None:
    dead = subprocess.Popen(["true"])
    dead.wait()
    slots = tmp_path / "slots"
    slots.mkdir()
    (slots / "t-0.lock").write_text(f"{dead.pid}\n")
    assert _slot_free(tmp_path)


def test_a_group_that_already_ended_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """macOS refuses (EPERM) a signal to a group of exited, unreaped processes; the wrapper must still free its slot."""
    spec = importlib.util.spec_from_file_location("at_most", Path(__file__).parents[1] / "at-most.py")
    assert spec and spec.loader
    at_most = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(at_most)

    def refused(pgid: int, sig: int) -> None:
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(os, "killpg", refused)
    at_most.kill_group(12345)


def test_a_command_inside_a_slot_that_asks_for_the_same_kind_runs_at_once(tmp_path: Path) -> None:
    inner = f"{sys.executable} {SCRIPT} 1 t -- echo inner"
    outer = [sys.executable, str(SCRIPT), "1", "t", "--", "sh", "-c", inner]
    ran = subprocess.run(outer, env=_env(tmp_path), capture_output=True, text=True, timeout=20, check=False)
    assert ran.returncode == 0 and "inner" in ran.stdout, ran
