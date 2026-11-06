"""ci.yml's plan (scripts/ci-plan.sh), by failure mode: a full plan leaves out a suite `make verify` runs, so a pull
request goes green on a red suite; a long suite is not split, so the run waits on it; a narrow change runs the repo
job meant for a full plan."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

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
