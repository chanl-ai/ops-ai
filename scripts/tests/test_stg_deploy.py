"""deploy/fly/stg_deploy.sh with every outside tool replaced by a stub that logs its command line. Failure modes: a
rollback that repeats the grants (a failed schema dump then fails the rollback too); a normal deploy that reuses a
pushed image (SKIP_BUILD=1) and so skips the grants. Nothing here reaches Fly or a database."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUBS = {
    "fly": 'echo "fly $*" >> "$LOG"\n'
    'case "$1 $2" in\n  "machine list") echo m1 ;;\n'
    '  "ssh console") [ "$HEALTH" = up ] && echo "ok processes" || exit 1 ;;\nesac\n',
    "docker": 'echo "docker $*" >> "$LOG"\n[ "$1" != port ] || echo 127.0.0.1:55432\n',
    "make": 'echo "make $*" >> "$LOG"\n',
    "psql": 'echo "psql" >> "$LOG"\n',
    "nc": "exit 0\n",
}


def run(tmp: Path, **env: str) -> tuple[subprocess.CompletedProcess[str], str]:
    repo = tmp / "repo"
    (repo / "deploy/fly").mkdir(parents=True)
    for name in ("stg_deploy.sh", "stg_env.sh", "fly.toml"):
        shutil.copy(ROOT / "deploy/fly" / name, repo / "deploy/fly" / name)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git[:3], "init", "-q"], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    bin_dir, conf = tmp / "bin", tmp / "conf"
    bin_dir.mkdir()
    conf.mkdir()
    for name, body in STUBS.items():
        (bin_dir / name).write_text("#!/bin/sh\n" + body)
        (bin_dir / name).chmod(0o755)
    (conf / "staging.env").write_text("STG_APP=stg-app\nSTG_DB_APP=stg-db\nSTG_APP_PREFIX=stg-\n")
    (conf / "staging-db-url.txt").write_text("postgresql://u:p@h:5432/d\n")
    log = tmp / "calls.log"
    log.touch()
    proc = subprocess.run(
        ["sh", str(repo / "deploy/fly/stg_deploy.sh")],
        env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "HOME": str(tmp),
            "OPS_STAGING_CONFIG": str(conf),
            "LOG": str(log),
            "STG_HEALTH_TIMEOUT": "0",
            **env,
        },
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    return proc, log.read_text()


def test_rollback_swaps_the_image_and_checks_health_only(tmp_path: Path) -> None:
    proc, calls = run(tmp_path, STG_ROLLBACK="1", HEALTH="up")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "--image registry.fly.io/stg-app:" in calls and "--build-only" not in calls
    assert "ssh console" in calls
    for step in ("docker run", "make -s", "psql", "fly proxy"):
        assert step not in calls, f"a rollback ran {step}:\n{calls}"
    assert "OCR" not in proc.stdout and "walk" not in proc.stdout


def test_deploy_of_a_pushed_image_still_applies_grants(tmp_path: Path) -> None:
    proc, calls = run(tmp_path, SKIP_BUILD="1", HEALTH="down")
    assert "--build-only" not in calls
    assert "docker run" in calls and "make -s" in calls and "psql" in calls, calls
    assert proc.returncode != 0  # stops at health: the stub machine never comes up
