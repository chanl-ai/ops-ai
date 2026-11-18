"""ci.yml's maintainer-review job, by failure mode: it ran the approval check and the history checks from the pull
request's own checkout, so a pull request could edit them to print `approved`. The job now replaces the gate's files
with the base revision's before it runs them, and says so when the base has no gate yet (the pull request adding it)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
GATE = "scripts/check_review_approval.py"
# What the job runs, directly or through `make checks-history`: a pull request that can edit one of these picks its
# own verdict.
MUST_BE_THE_BASES = (
    GATE,
    "scripts/baseline_history.py",
    "scripts/check_access_exceptions.py",
    "scripts/check_portable_store.py",
    "scripts/check_config_literals.py",
    "scripts/keep_going.sh",
    "make/checks.mk",
    "Makefile",
    "packages/ops_store/tests/test_isolation_sites.py",
    "packages/ops_store/tests/test_relay_sites.py",
    "packages/ops_store/tests/test_loop_health.py",
    "deploy/database/tests/test_indexes.py",
)


def steps() -> list[dict[str, Any]]:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    return workflow["jobs"]["maintainer-review"]["steps"]


def gate_step() -> dict[str, Any]:
    found = [s for s in steps() if "base revision" in str(s.get("name", ""))]
    assert len(found) == 1, "the maintainer-review job has no step that takes the base revision's gate"
    return found[0]


def test_the_gate_step_comes_before_the_step_that_runs_the_gate_and_covers_every_file_it_runs() -> None:
    names = [s.get("name", "") for s in steps()]
    run = next(i for i, n in enumerate(names) if "approval" in n)
    assert names.index(gate_step()["name"]) < run
    listed = gate_step()["env"]["TRUSTED"].split()
    assert [p for p in MUST_BE_THE_BASES if p not in listed] == []
    assert "--head" in steps()[run]["run"], "an approval is read against the pull request's head commit"


def _git(repo: Path, *args: str) -> str:
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True, env=env)
    return done.stdout.strip()


def _run_step(repo: Path, base: str) -> subprocess.CompletedProcess[str]:
    step = gate_step()
    env = {**os.environ, **step["env"], "BASE_SHA": base, "GITHUB_ENV": str(repo / "github-env.txt")}
    return subprocess.run(
        ["bash", "-e", "-c", step["run"]], cwd=repo, env=env, capture_output=True, text=True, check=False
    )


def _repo(tmp_path: Path, with_gate: bool) -> str:
    _git(tmp_path, "init", "-q")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "make").mkdir()
    (tmp_path / "other.txt").write_text("x\n")
    if with_gate:
        (tmp_path / GATE).write_text("print('base')\n")
        (tmp_path / "make/checks.mk").write_text("base\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    return _git(tmp_path, "rev-parse", "HEAD")


def test_a_pull_request_that_edits_the_gate_runs_the_bases_copy(tmp_path: Path) -> None:
    base = _repo(tmp_path, with_gate=True)
    (tmp_path / GATE).write_text("print('approved')\n")
    (tmp_path / "make/checks.mk").write_text("approved\n")
    _git(tmp_path, "commit", "-qam", "a pull request that prints approved")
    done = _run_step(tmp_path, base)
    assert done.returncode == 0, done.stderr
    assert (tmp_path / GATE).read_text() == "print('base')\n"
    assert (tmp_path / "make/checks.mk").read_text() == "base\n"


def test_the_pull_request_that_adds_the_gate_runs_its_own_and_says_so(tmp_path: Path) -> None:
    base = _repo(tmp_path, with_gate=False)
    (tmp_path / GATE).write_text("print('new')\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "adds the gate")
    done = _run_step(tmp_path, base)
    assert done.returncode == 0, done.stderr
    assert (tmp_path / GATE).read_text() == "print('new')\n"
    assert "::warning" in done.stdout
