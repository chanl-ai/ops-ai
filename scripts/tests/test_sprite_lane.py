"""scripts/sprite-lane.sh creates one sprite and does not attach the local checkout."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "sprite-lane.sh"


def fake_sprite(bin_dir: Path, log: Path) -> None:
    exe = bin_dir / "sprite"
    exe.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\nexit 0\n')
    exe.chmod(0o755)


def fake_box_sprite(bin_dir: Path, log: Path, existing: str, status: str) -> None:
    """A sprite CLI that lists `existing` (a name, or none), reports `status` for it and logs every other call."""
    exe = bin_dir / "sprite"
    exe.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        f'  list) printf "%s   \\n" "{existing}" ;;\n'
        '  api) printf \'Calling API\\n{"url":"https://b-x.sprites.app/","status":"' + status + "\"}' ;;\n"
        f'  *) printf "%s\\n" "$*" >> "{log}" ;;\n'
        "esac\n"
    )
    exe.chmod(0o755)


def run(tmp_path: Path, *args: str, box: tuple[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    log = tmp_path / "log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    if box is None:
        fake_sprite(bin_dir, log)
    else:
        fake_box_sprite(bin_dir, log, *box)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "SPRITE_ORG": "chanl",
        "BOX_SLEEP_WAIT": "1",
        "BOX_SLEEP_POLL": "1",
    }
    result = subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    result.log = log.read_text() if log.exists() else ""  # type: ignore[attr-defined]
    return result


def test_add_creates_one_sprite_and_does_not_attach(tmp_path: Path) -> None:
    result = run(tmp_path, "add", "demo")
    assert result.returncode == 0, result.stderr
    assert result.log == "create --skip-console -o chanl ops-ai-lane-demo\n"
    assert " use" not in result.log


def test_exec_does_not_forward_ports(tmp_path: Path) -> None:
    result = run(tmp_path, "exec", "demo", "--", "git", "status")
    assert result.returncode == 0, result.stderr
    assert result.log == "exec -o chanl -s ops-ai-lane-demo --no-port-forward -- git status\n"


def test_bad_name_is_refused(tmp_path: Path) -> None:
    result = run(tmp_path, "add", "Demo")
    assert result.returncode == 1
    assert result.log == ""


def test_up_wakes_an_existing_box_and_does_not_create_another(tmp_path: Path) -> None:
    result = run(tmp_path, "up", "ops-ai-box-1", "main", box=("ops-ai-box-1", "cold"))
    assert result.returncode == 0, result.stderr
    assert "create" not in result.log
    assert "config update -o chanl -s ops-ai-box-1 --url-auth sprite" in result.log
    assert "BRANCH=main OPS_PUBLIC_ORIGIN=https://b-x.sprites.app" in result.log


def test_up_creates_a_missing_box(tmp_path: Path) -> None:
    result = run(tmp_path, "up", "ops-ai-box-1", box=("", "cold"))
    assert result.returncode == 0, result.stderr
    assert result.log.startswith("create --skip-console -o chanl ops-ai-box-1\n")


def test_sleep_fails_when_the_box_does_not_go_cold(tmp_path: Path) -> None:
    result = run(tmp_path, "sleep", "ops-ai-box-1", box=("ops-ai-box-1", "warm"))
    assert result.returncode == 1
    assert "still warm" in result.stderr


def test_sleep_leaves_the_stack_running_and_stop_does_not(tmp_path: Path) -> None:
    slept = run(tmp_path / "a", "sleep", "ops-ai-box-1", box=("ops-ai-box-1", "cold"))
    assert slept.returncode == 0, slept.stderr
    assert "ops-ai-box-1: cold" in slept.stdout
    assert "make -s down" not in slept.log
    stopped = run(tmp_path / "b", "stop", "ops-ai-box-1", box=("ops-ai-box-1", "cold"))
    assert stopped.returncode == 0, stopped.stderr
    assert "make -s down" in stopped.log
