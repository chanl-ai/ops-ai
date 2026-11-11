"""A fix(qa): commit is held to 20 changed lines in plan-named source files plus any test, use case, seed or fixture
files. Each case stages a change in a scratch repository and runs scripts/qa-fix-check.mjs as the commit-msg hook does:
a 15-line fix in a plan file passes; a 40-line fix, a file outside the plan, and a missing plan list are refused;
a commit that is not fix(qa): is not looked at."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

CHECK = Path(__file__).resolve().parents[1] / "qa-fix-check.mjs"
PLAN = "apps/console/src/page.tsx"


def run(tmp_path: Path, files: dict[str, int], subject: str = "fix(qa): stale label", plan: str | None = PLAN):
    """Stage `files` (path -> lines added to an existing 50-line file) and run the check."""
    repo = tmp_path / "repo"
    repo.mkdir()
    g = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)  # noqa: E731
    g("init", "-q")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    for path in files:
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text("".join(f"old {i}\n" for i in range(50)))
    g("add", ".")
    g("commit", "-qm", "base")
    for path, n in files.items():
        with (repo / path).open("a") as f:
            f.write("".join(f"new {i}\n" for i in range(n)))
    g("add", ".")
    msg = repo / "MSG"
    msg.write_text(subject + "\n")
    env = {k: v for k, v in os.environ.items() if k != "QA_PLAN_FILES"}
    if plan is not None:
        env["QA_PLAN_FILES"] = plan
    cmd = ["node", str(CHECK), "--commit", str(msg)]
    return subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True, check=False)


def test_a_15_line_fix_in_a_plan_file_passes(tmp_path: Path) -> None:
    assert run(tmp_path, {PLAN: 15}).returncode == 0


def test_tests_seed_and_fixtures_are_not_counted(tmp_path: Path) -> None:
    files = {
        PLAN: 15,
        "docs/usecases/console/scripts/t.mjs": 90,
        "services/a/seed/x.json": 90,
        "services/a/tests/test_x.py": 90,
    }
    assert run(tmp_path, files).returncode == 0


def test_a_40_line_fix_is_refused(tmp_path: Path) -> None:
    done = run(tmp_path, {PLAN: 40})
    assert done.returncode == 1 and "40 changed source lines" in done.stderr


def test_the_limit_is_total_across_files(tmp_path: Path) -> None:
    done = run(tmp_path, {PLAN: 12, "apps/console/src/b.tsx": 12}, plan=f"{PLAN} apps/console/src/b.tsx")
    assert done.returncode == 1 and "24 changed source lines" in done.stderr


@pytest.mark.parametrize("plan", ["apps/console/src/other.tsx", None])
def test_a_file_outside_the_plan_is_refused(tmp_path: Path, plan: str | None) -> None:
    done = run(tmp_path, {PLAN: 5}, plan=plan)
    assert done.returncode == 1 and "plan does not name it" in done.stderr


def test_other_commits_are_not_checked(tmp_path: Path) -> None:
    assert run(tmp_path, {PLAN: 40}, subject="fix(console): big change", plan=None).returncode == 0
