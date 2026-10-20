"""scripts/keep_going.sh (c-367), by failure mode: a failed check that stops the run so the checks after it never run,
and a run with a failed check that ends green."""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "keep_going.sh"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SCRIPT), *args], capture_output=True, text=True, check=False)


def test_every_check_runs_and_the_report_lists_each_failure_and_fails(tmp_path: Path) -> None:
    failed = str(tmp_path / "failed")
    assert run(failed, "sh", "-c", "exit 1").returncode == 0, "a failed check lets the next one run"
    after = run(failed, "sh", "-c", "echo next ran")
    assert after.returncode == 0 and "next ran" in after.stdout
    assert run(failed, "sh", "-c", "exit 3").returncode == 0
    report = run("--report", failed)
    assert report.returncode == 1, report.stdout
    assert "2 check(s) failed" in report.stdout and "(exit 1)" in report.stdout and "(exit 3)" in report.stdout


def test_a_run_whose_checks_all_pass_reports_green(tmp_path: Path) -> None:
    failed = str(tmp_path / "failed")
    assert run(failed, "true").returncode == 0
    report = run("--report", failed)
    assert (report.returncode, report.stdout.strip()) == (0, "verify: every check passed")
