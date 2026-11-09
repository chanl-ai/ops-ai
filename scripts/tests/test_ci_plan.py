"""ci.yml's plan (scripts/ci-plan.sh), by failure mode: a full plan leaves out a suite `make verify` runs, so a pull
request goes green on a red suite; a long suite is not split, so the run waits on it; a narrow change runs the repo
job meant for a full plan; the one required check, ci-ok, misses a job or passes when a job failed or was cancelled."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
# Run under `make python-verify VERIFY_POOL=...` (ci.yml's repo job), the inner make would inherit that override
# through MAKEFLAGS and print the job's pool, not the full one the plan is built from.
CLEAN_MAKE_ENV = {k: v for k, v in os.environ.items() if k not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL")}


def plan(tmp_path: Path, *changed: str) -> dict[str, str]:
    listed = tmp_path / "changed.txt"
    listed.write_text("\n".join(changed) + "\n", encoding="utf-8")
    out = subprocess.run(
        ["bash", "scripts/ci-plan.sh", str(listed)],
        cwd=ROOT,
        env=CLEAN_MAKE_ENV,
        capture_output=True,
        text=True,
        check=True,
    )
    return dict(line.split("=", 1) for line in out.stdout.splitlines() if "=" in line)


def verify_pool() -> set[str]:
    out = subprocess.run(
        ["make", "-s", "-f", "make/python.mk", "-f", "/dev/stdin", "print-pool"],
        cwd=ROOT,
        env=CLEAN_MAKE_ENV,
        input="print-pool: ; @echo $(VERIFY_POOL)\n",
        capture_output=True,
        text=True,
        check=True,
    )
    return set(out.stdout.split())


def test_a_full_plan_runs_every_suite_make_verify_runs(tmp_path: Path) -> None:
    p = plan(tmp_path, "make/env.mk")
    assert p["full"] == "true", p
    jobs = json.loads(p["service_jobs"])
    services = {f"pool-{j['service'].removesuffix('-service')}" for j in jobs}
    assert services | set(p["repo_pool"].split()) == verify_pool(), p
    assert (p["console"], p["docs"]) == ("true", "true"), p


def test_the_long_suites_run_as_shards_beside_their_checks(tmp_path: Path) -> None:
    jobs = json.loads(plan(tmp_path, "make/env.mk")["service_jobs"])
    agents = sorted(j["part"] for j in jobs if j["service"] == "agents-service")
    assert agents == ["checks"] + [f"test {i}/6" for i in range(1, 7)], agents
    tools = sorted(j["part"] for j in jobs if j["service"] == "tools-service")
    assert tools == ["checks", "test 1/5", "test 2/5", "test 3/5", "test 4/5", "test 5/5"], tools


def test_a_service_change_runs_that_service_and_no_repo_job(tmp_path: Path) -> None:
    p = plan(tmp_path, "services/kb-service/src/ops_kb/app.py")
    assert (p["full"], p["repo_pool"]) == ("false", ""), p
    assert json.loads(p["service_jobs"]) == [{"service": "kb-service", "part": "verify"}], p


def _ci_ok() -> tuple[dict[str, Any], set[str]]:
    jobs: dict[str, Any] = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    return jobs["ci-ok"], set(jobs) - {"ci-ok"}


def _gate(needs: dict[str, str]) -> int:
    script = _ci_ok()[0]["steps"][0]["run"]
    env = {"NEEDS": json.dumps({k: {"result": v} for k, v in needs.items()}, indent=2), "PATH": os.environ["PATH"]}
    return subprocess.run(["bash", "-c", script], env=env, capture_output=True, check=False).returncode


def test_one_check_named_ci_ok_waits_for_every_other_job_whatever_they_did() -> None:
    job, others = _ci_ok()
    assert (job.get("name"), job.get("if")) == ("ci-ok", "always()"), job
    assert set(job["needs"]) == others, set(job["needs"]) ^ others


def test_ci_ok_fails_on_a_failed_or_cancelled_job_and_passes_a_skipped_one() -> None:
    assert _gate({"plan": "success", "checks": "skipped", "repo": "success"}) == 0
    assert _gate({"plan": "success", "checks": "failure"}) == 1
    assert _gate({"plan": "success", "console": "cancelled"}) == 1
