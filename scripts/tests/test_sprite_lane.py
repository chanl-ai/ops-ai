"""scripts/sprite-lane.sh creates one sprite and does not attach the local checkout."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "sprite-lane.sh"


def fake_sprite(bin_dir: Path, log: Path) -> None:
    exe = bin_dir / "sprite"
    exe.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{log}"\n'
        "exit 0\n"
    )
    exe.chmod(0o755)


def run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    log = tmp_path / "log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_sprite(bin_dir, log)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}", "SPRITE_ORG": "chanl"}
    result = subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
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
