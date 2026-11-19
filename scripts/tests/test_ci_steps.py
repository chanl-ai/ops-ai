"""ci_steps.py: a CI step with no twin, a list entry CI no longer has, and a plan that runs nothing."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ci_steps

ROOT = Path(__file__).resolve().parents[2]


def test_a_ci_step_with_no_twin_is_refused() -> None:
    workflow, listed = ci_steps.load()
    workflow["jobs"]["docs"]["steps"].append({"run": "echo planted"})
    assert any("echo planted" in p for p in ci_steps.check(workflow, listed))


def test_a_listed_step_ci_no_longer_has_is_refused() -> None:
    workflow, listed = ci_steps.load()
    listed["docs"].append({"step": "gone step", "twin": "true"})
    listed["gone-job"] = [{"step": "x", "twin": "true"}]
    problems = ci_steps.check(workflow, listed)
    assert any("gone step" in p for p in problems) and any("gone-job" in p for p in problems)


def test_plan_prints_the_twins_and_runs_nothing() -> None:
    out = subprocess.run(
        ["make", "-s", "ci-local", "PLAN=1", "JOB=docs"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    assert out.strip() == "[docs] make -s docs-verify"
