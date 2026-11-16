"""The one list of checks (make/checks.mk), by failure mode: a check added to one of the places that run checks and not
the others, so a pull request, `make verify` and pre-commit each pass a different set; a plan for a one-file change that
skips the checks job; and a pipeline job the standards name (staging that skips when the plan skipped a job, the
both-database store run, the release proof) that is missing or has the wrong trigger."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
# Under `make python-verify` (CI's repo job) the inner make would inherit the job's overrides.
CLEAN_ENV = {k: v for k, v in os.environ.items() if k not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL")}
CI: dict[str, Any] = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
# PyYAML reads the bare key `on` as True.
TRIGGERS: dict[str, Any] = CI.get("on") or CI[True]


def make(*args: str) -> str:
    done = subprocess.run(["make", "-s", *args], cwd=ROOT, env=CLEAN_ENV, capture_output=True, text=True, check=True)
    return done.stdout


def listed() -> dict[str, str]:
    """Check name -> the command it runs, from `make checks-list`."""
    return dict(line.split("\t", 1) for line in make("checks-list").splitlines())


def plan(tmp_path: Path, *changed: str) -> dict[str, str]:
    listing = tmp_path / "changed.txt"
    listing.write_text("\n".join(changed) + "\n")
    out = subprocess.run(
        ["bash", "scripts/ci-plan.sh", str(listing)],
        cwd=ROOT,
        env=CLEAN_ENV,
        capture_output=True,
        text=True,
        check=True,
    )
    return dict(line.split("=", 1) for line in out.stdout.splitlines() if "=" in line)


# What `make verify`, CI's checks job and pre-commit ran before the list, and the checks the standards added.
REQUIRED = {
    "access-exceptions", "access-exceptions-commits", "access-exceptions-self-test", "portable-store",
    "portable-store-commits", "config-literals", "config-literals-commits", "typed-boundaries", "isolation-markings",
    "isolation-sites", "store-inventory", "roles-matrix", "sbom", "k8s-base", "lint-imports", "sdk-drift",
    "changelog-entries", "console-standards",
}  # fmt: skip


def test_every_listed_check_runs_when_make_checks_runs() -> None:
    commands = listed()
    assert set(commands) >= REQUIRED, f"missing from the list: {sorted(REQUIRED - set(commands))}"
    dry = make("-n", "checks")
    missing = [name for name, command in commands.items() if command not in dry]
    assert missing == [], f"`make checks` does not run {missing}"


def test_the_checks_job_runs_the_list_on_a_one_file_service_change(tmp_path: Path) -> None:
    p = plan(tmp_path, "services/kb-service/src/ops_kb/app.py")
    assert p["full"] == "false", p
    job = CI["jobs"]["checks"]
    # The job's own condition holds for a plan that is not full, and it runs the list, not a copy of it.
    assert job["if"] == "needs.plan.outputs.full != 'true'"
    assert "make -s checks" in [step.get("run") for step in job["steps"]]
    assert job["steps"][1].get("with", {}).get("fetch-depth", 0) == 0 or job["steps"][0]["with"]["fetch-depth"] == 0
    assert any(step.get("with", {}).get("node") == "true" for step in job["steps"]), (
        "the SDK and console checks need node"
    )


def test_every_other_place_that_checks_runs_the_same_list(tmp_path: Path) -> None:
    # A full plan: the repo job runs python-verify, whose body calls the list.
    assert plan(tmp_path, "make/env.mk")["full"] == "true"
    assert "run: make python-verify" in (ROOT / ".github/workflows/ci.yml").read_text()
    assert "$(KEEP) $(MAKE) -s checks" in (ROOT / "make/python.mk").read_text()
    # What changed since a base, and the commit being made.
    assert "\nmake -s checks\n" in (ROOT / "scripts/verify-changed.sh").read_text()
    staged = (ROOT / "scripts/verify-staged.sh").read_text()
    assert "checks STAGED=1" in staged
    # No check of the list is still written out beside it.
    for old in ("check_typed_boundaries.py --strict", "check_portable_store.py --strict", "lint-imports"):
        assert old not in (ROOT / "scripts/verify-changed.sh").read_text(), old


def staged_names(tmp_path: Path, *paths: str) -> list[str]:
    """The checks `make checks STAGED=1` starts for these staged paths, with every tool replaced by `echo`."""
    staged = tmp_path / "staged.txt"
    staged.write_text("\n".join(paths) + "\n")
    out = make("checks", "STAGED=1", f"STAGED_FILES={staged}", "PY=echo", "PYTEST=echo", "LINT_IMPORTS=echo")
    return [line.removeprefix("== ") for line in out.splitlines() if line.startswith("== ")]


def test_staged_runs_a_check_only_when_a_staged_path_can_change_it(tmp_path: Path) -> None:
    assert staged_names(tmp_path, "docs/usecases/README.md") == []
    names = staged_names(tmp_path, "services/kb-service/src/ops_kb/app.py")
    assert {"typed-boundaries", "config-literals", "access-exceptions", "lint-imports"} <= set(names), names
    assert "sdk-drift" not in names and "changelog-entries" not in names, names
    # A history check can only change when a baseline file is staged.
    assert "config-literals-commits" not in names
    assert "config-literals-commits" in staged_names(tmp_path, "services/kb-service/config-literals-baseline.txt")


def test_staging_does_not_skip_when_the_plan_skipped_a_job() -> None:
    assert "!cancelled()" in CI["jobs"]["staging"]["if"]
    assert CI["jobs"]["staging"]["needs"] == "ci-ok"


def test_the_both_database_run_and_the_release_proof_are_required_with_their_triggers() -> None:
    jobs = CI["jobs"]
    assert {"store-mssql", "release-proof"} <= set(jobs["ci-ok"]["needs"])
    assert "pull_request" in TRIGGERS
    # On every pull request and push: no `if`; the run names SQL Server and fails on a skip.
    assert "if" not in jobs["store-mssql"]
    steps = "\n".join(str(step.get("run", "")) for step in jobs["store-mssql"]["steps"])
    assert "OPS_MSSQL_SERVER" in steps and "mssql/server:2025-latest@sha256:" in steps and "SKIPPED" in steps
    for package in ("ops_store", "ops_service_kit", "ops_identity"):
        assert package in steps
    # A pull request into main is a release.
    assert jobs["release-proof"]["if"] == "github.event_name == 'pull_request' && github.base_ref == 'main'"
    release = "\n".join(str(step.get("run", "")) for step in jobs["release-proof"]["steps"])
    assert "make db-scripts-proof FROM=" in release and "make install-proof" in release


def test_no_workflow_deploys_production_until_the_owner_has_set_up_the_environment() -> None:
    """A workflow cannot see the `production` environment's reviewers or where the deploy token lives, so one that ran
    on a repository variable could deploy with no approval. It returns with a guard that reads the environment's rules
    (docs/deploy/fly-staging.md, "Production on GitHub")."""
    deploying = [
        path.name
        for path in (ROOT / ".github/workflows").glob("*.yml")
        if re.search(r"environment:\s*(name:\s*)?['\"]?production", path.read_text())
    ]
    assert deploying == [], deploying
    assert not (ROOT / ".github/workflows/deploy-prod.yml").exists()
