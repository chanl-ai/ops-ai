"""The wait guard, driven the way Claude Code drives it: JSON on stdin, exit 2 and a reason on stderr. By failure mode:
the whole suite runs from an agent; a named file is refused by mistake; the owner is blocked; text inside a commit
message trips a rule; a registered hook is missing from the settings."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts" / "agent-guard.py"


def run(command: str, **env: str) -> subprocess.CompletedProcess[str]:
    clean = {k: v for k, v in os.environ.items() if k not in ("CL_AGENT", "CL_AGENT_RUN")}
    return subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps({"tool_input": {"command": command}}),
        capture_output=True,
        text=True,
        env={**clean, **env},
        check=False,
    )


def test_an_agent_cannot_run_a_whole_suite_and_is_told_the_command_to_run_instead() -> None:
    for command in ("uv run pytest", "make test PKG=services/kb-service", "pnpm verify"):
        r = run(command, CL_AGENT="builder-c-1")
        assert r.returncode == 2, command
        assert "make test" in r.stderr and len(r.stderr.strip().splitlines()) == 1, r.stderr


def test_an_agent_can_run_a_named_file_and_the_impacted_pick() -> None:
    assert run("uv run pytest services/kb-service/tests/test_x.py -q", CL_AGENT="b").returncode == 0
    assert run("make test PKG=services/kb-service T=tests/test_x.py", CL_AGENT="b").returncode == 0
    assert run("make test-impacted BASE=origin/main", CL_AGENT="b").returncode == 0


def test_a_sleep_over_a_minute_is_refused_and_a_short_one_is_not() -> None:
    assert run("sleep 120", CL_AGENT_RUN="r1").returncode == 2
    assert run("for i in $(seq 1 20); do sleep 30; done", CL_AGENT_RUN="r1").returncode == 2
    assert run("sleep 45", CL_AGENT_RUN="r1").returncode == 0


def test_the_owner_is_never_blocked() -> None:
    for command in ("pytest", "pnpm verify", "sleep 600"):
        assert run(command).returncode == 0, command


def test_words_inside_a_commit_message_are_not_commands() -> None:
    assert run("git commit -m 'drop pnpm verify; sleep 300; pytest'", CL_AGENT="b").returncode == 0


def test_the_self_test_covers_every_rule() -> None:
    r = subprocess.run([sys.executable, str(GUARD), "--self-test"], capture_output=True, text=True, check=False)
    assert r.returncode == 0, r.stdout
