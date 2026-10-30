"""A package change runs what depends on it, not the whole suite (c-566), by failure mode: a dependant reached only
through another package is skipped; a package nothing depends on still forces a full run; a changed directory that is
no workspace member is skipped instead of running everything."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dependants import dependants  # pyright: ignore[reportMissingImports]

ROOT = Path(__file__).resolve().parents[2]


def test_a_package_reaches_the_services_that_use_it_through_other_packages() -> None:
    reached, unknown = dependants(["packages/ops_agent_kernel"])
    # tools-service lists ops-agent-kernel itself; agents-service also reaches it through ops_engine.
    assert {"packages/ops_engine", "services/agents-service", "services/tools-service"} <= set(reached)
    assert "services/platform-service" not in reached and not unknown


def test_direct_stops_at_the_members_that_list_the_package_themselves() -> None:
    # runner-service reaches ops_store only through another package; the push check leaves it to the full run.
    direct, _ = dependants(["packages/ops_store"], direct=True)
    reached, _ = dependants(["packages/ops_store"])
    assert "services/runner-service" in reached and "services/runner-service" not in direct
    assert {"packages/ops_store", "services/agents-service"} <= set(direct)


def test_a_directory_that_is_no_member_is_named_unknown() -> None:
    reached, unknown = dependants(["packages/usecase-runner", "packages/ops_signin"])
    assert unknown == ["packages/usecase-runner"] and reached == ["packages/ops_signin", "services/platform-service"]


def plan(tmp_path: Path, *changed: str, depth: str = "", show: str = "1") -> str:
    listed = tmp_path / "changed.txt"
    listed.write_text("\n".join(changed) + "\n", encoding="utf-8")
    out = subprocess.run(
        ["bash", "scripts/verify-changed.sh", str(listed)],
        cwd=ROOT,
        env={**os.environ, "VERIFY_CHANGED_PLAN": show, "VERIFY_CHANGED_DEPTH": depth},
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return next(line for line in out.splitlines() if line.startswith(("plan:", "jobs:")))


def test_a_package_change_plans_its_dependants_not_the_full_suite(tmp_path: Path) -> None:
    assert plan(tmp_path, "packages/ops_signin/src/ops_signin/__init__.py") == (
        "plan: packages [packages/ops_signin] services [platform-service]"
    )


def test_the_push_depth_plans_only_direct_dependants(tmp_path: Path) -> None:
    pushed = plan(tmp_path, "packages/ops_store/src/ops_store/__init__.py", depth="direct")
    assert "agents-service" in pushed and "runner-service" not in pushed, pushed


def test_a_service_only_change_plans_that_service(tmp_path: Path) -> None:
    assert plan(tmp_path, "services/tools-service/scripts/reimport_bank_module.py", depth="direct") == (
        "plan: packages [] services [tools-service]"
    )


def test_the_planned_suites_are_the_jobs_that_start(tmp_path: Path) -> None:
    # A job list built from a failing substitution started nothing, and the run still ended green.
    assert plan(tmp_path, "services/tools-service/src/ops_tools/app.py", show="jobs") == "jobs: tools-service"
    pushed = plan(tmp_path, "packages/ops_signin/src/ops_signin/__init__.py", depth="direct", show="jobs")
    assert pushed == "jobs: platform-service ops_signin"


def test_an_unknown_python_package_still_runs_everything(tmp_path: Path) -> None:
    assert plan(tmp_path, "packages/ops_not_a_member/src/x.py") == "plan: full"
