"""ci.yml's plan (scripts/ci-plan.sh), by failure mode: a full plan leaves out a suite `make verify` runs, so a pull
request goes green on a red suite; a long suite is not split, so the run waits on it; a narrow change runs the repo
job meant for a full plan, or a documents-only change runs code jobs; [ci full] does not run everything; the one
required check, ci-ok, misses a job or passes when a job failed or was cancelled."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ci_local

ROOT = Path(__file__).resolve().parents[2]
# Run under `make python-verify VERIFY_POOL=...` (ci.yml's repo job), the inner make would inherit that override
# through MAKEFLAGS and print the job's pool, not the full one the plan is built from.
CLEAN_MAKE_ENV = {k: v for k, v in os.environ.items() if k not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL")}


def plan(tmp_path: Path, *changed: str, ref: str = "", full: str = "", event: str = "") -> dict[str, str]:
    listed = tmp_path / "changed.txt"
    listed.write_text("\n".join(changed) + "\n", encoding="utf-8")
    out = subprocess.run(
        ["bash", "scripts/ci-plan.sh", str(listed)],
        cwd=ROOT,
        env={**CLEAN_MAKE_ENV, "GITHUB_REF": ref, "CI_FULL": full, "GITHUB_EVENT_NAME": event},
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


def test_a_documents_only_change_runs_only_the_docs_job_and_a_service_change_runs_sql_server(tmp_path: Path) -> None:
    p = plan(tmp_path, "docs/guide/plugins.md", "README.md")
    picked = (p["code"], p["mssql"], p["console"], p["scripts"], p["service_jobs"], p["packages"], p["docs"])
    assert picked == ("false", "false", "false", "false", "[]", "[]", "true"), p
    assert plan(tmp_path, "services/kb-service/src/ops_kb/app.py")["mssql"] == "true"
    assert plan(tmp_path, "apps/console/src/app.tsx")["mssql"] == "false"


def test_ci_full_runs_every_job_whatever_changed(tmp_path: Path) -> None:
    p = plan(tmp_path, "docs/guide/plugins.md", full="true")
    assert (p["full"], p["code"], p["mssql"], p["console"]) == ("true", "true", "true", "true"), p


def test_a_release_or_hotfix_branch_runs_every_job_whatever_changed(tmp_path: Path) -> None:
    for ref in ("refs/heads/release/1.2.0", "refs/heads/hotfix/1.2.1"):
        p = plan(tmp_path, "docs/deploy/release.md", ref=ref)
        assert (p["full"], p["release"], p["console"], p["docs"]) == ("true", "true", "true", "true"), p
        assert {j["service"] for j in json.loads(p["service_jobs"])} >= {"agents-service", "kb-service"}, p
    assert plan(tmp_path, "docs/deploy/release.md", ref="refs/heads/develop")["release"] == "false"


def _ci_ok() -> tuple[dict[str, Any], set[str]]:
    jobs: dict[str, Any] = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    # A job that needs ci-ok (the staging deploy) runs after the gate, so the gate cannot wait for it.
    after = {name for name, j in jobs.items() if "ci-ok" in (j.get("needs") or [])}
    return jobs["ci-ok"], set(jobs) - {"ci-ok"} - after


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


def _plan_step() -> dict[str, Any]:
    steps = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]["plan"]["steps"]
    return next(s for s in steps if s.get("id") == "plan")


def test_a_push_run_has_its_own_concurrency_group_so_a_queued_push_is_not_dropped() -> None:
    conc = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["concurrency"]
    # One group per ref keeps one pending run and drops the rest, even with cancel-in-progress off.
    assert "github.sha" in conc["group"] and "github.ref" not in conc["group"], conc
    assert "pull_request" in str(conc["cancel-in-progress"]) and "push" not in str(conc["cancel-in-progress"]), conc


def test_a_merge_queue_run_is_planned_like_a_pull_request_from_the_queue_base() -> None:
    ci = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    # PyYAML reads the key `on` as True.
    assert "merge_group" in ci[True], ci[True]
    assert "github.event.merge_group.base_sha" in ci["env"]["BASE_SHA"], ci["env"]["BASE_SHA"]
    # The last-green plan belongs to a push only; a queue run taking it would be planned from an old commit.
    assert 'GITHUB_EVENT_NAME" = push' in _plan_step()["run"]
    # ci-ok runs always and waits on every job, so it reports on the queue's run.
    assert ci["jobs"]["ci-ok"]["if"] == "always()" and "plan" in ci["jobs"]["ci-ok"]["needs"]


def test_the_plan_of_a_develop_push_starts_from_the_last_green_commit_not_the_event_before() -> None:
    run = _plan_step()["run"]
    assert "ci-last-green.sh" in run and "CI_FULL=true" in run, run


def _repo_with_commits(tmp_path: Path, n: int) -> list[str]:
    def git(*a: str) -> str:
        return subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, text=True, check=True).stdout.strip()

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    shas = []
    for i in range(n):
        (tmp_path / "f").write_text(str(i))
        git("add", "f")
        git("commit", "-qm", str(i))
        shas.append(git("rev-parse", "HEAD"))
    return shas


def _last_green(tmp_path: Path, current: str, runs: list[dict[str, str]]) -> str:
    return subprocess.run(
        ["bash", str(ROOT / "scripts/ci-last-green.sh"), current],
        cwd=tmp_path,
        input=json.dumps({"workflow_runs": runs}),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_last_green_skips_the_current_commit_and_unknown_ones_and_is_empty_when_none(tmp_path: Path) -> None:
    c0, c1, c2 = _repo_with_commits(tmp_path, 3)
    runs = [
        {"head_sha": c2, "conclusion": "success", "created_at": "2026-11-22T03"},
        {"head_sha": "f" * 40, "conclusion": "success", "created_at": "2026-11-22T02"},
        {"head_sha": c1, "conclusion": "success", "created_at": "2026-11-22T01"},
        {"head_sha": c0, "conclusion": "success", "created_at": "2026-11-22T00"},
    ]
    assert _last_green(tmp_path, c2, runs) == c1
    assert _last_green(tmp_path, c2, []) == ""


def _runs(job: str, p: dict[str, str]) -> bool:
    """Whether ci.yml starts the job for this plan, read from the job's own `if:` (ci_local's reader)."""
    cond = ci_local.condition(yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"][job].get("if"), p)
    assert cond is not None, f"{job}'s condition reads GitHub's context, so a test cannot tell"
    return cond


def test_a_pull_request_skips_the_slow_jobs_that_the_merge_queue_and_develop_run(tmp_path: Path) -> None:
    # A service change plans store-mssql; a change of the make files plans the full repo job.
    for changed in ("services/kb-service/src/ops_kb/app.py", "make/env.mk"):
        pr = plan(tmp_path, changed, event="pull_request")
        assert (pr["heavy"], _runs("store-mssql", pr), _runs("repo", pr)) == ("false", False, False), pr
        for event in ("merge_group", "push"):
            assert plan(tmp_path, changed, event=event)["heavy"] == "true"
    assert _runs("store-mssql", plan(tmp_path, "services/kb-service/src/ops_kb/app.py", event="merge_group"))
    assert _runs("repo", plan(tmp_path, "make/env.mk", event="push"))
    # Labelled ci:full, a pull request still runs everything.
    assert _runs("repo", plan(tmp_path, "make/env.mk", event="pull_request", full="true"))


def test_the_script_tests_and_release_proof_wait_for_heavy_and_a_pull_request_still_gets_ci_ok() -> None:
    jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())["jobs"]
    script_step = next(s for s in jobs["checks"]["steps"] if s.get("name") == "Script tests")
    assert "outputs.heavy == 'true'" in script_step["if"], script_step
    assert "outputs.heavy == 'true'" in jobs["release-proof"]["if"], jobs["release-proof"]["if"]
    # Skipped jobs pass the gate.
    assert _gate({"plan": "success", "repo": "skipped", "store-mssql": "skipped", "release-proof": "skipped"}) == 0


def test_the_repo_job_is_one_matrix_entry_per_suite_and_check(tmp_path: Path) -> None:
    p = plan(tmp_path, "make/env.mk")
    parts = [e["part"] for e in json.loads(p["repo_jobs"])]
    assert parts == [*p["repo_pool"].split(), "checks", "scripts", "sdk"], parts
    assert len(parts) >= 8 and plan(tmp_path, "docs/guide/plugins.md")["repo_jobs"] == "[]"
