#!/usr/bin/env python3
"""The local twin of every CI step, from one list (scripts/ci_steps.json).

  ci_steps.py --check              fail when a `run:` step in ci.yml has no twin and no no_local_twin reason, or the
                                   list names a job or step ci.yml no longer has
  ci_steps.py --run [--job J] [--plan]
                                   run each job's twins in ci.yml order (an identical command once), keep going past a
                                   failure and list them all at the end; --plan prints the commands and runs nothing
  ci_steps.py --self-test          plants one unlisted step and one stale entry and sees both refused

A step is named by its `name:`, else by the first line of its command.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/ci.yml"
LIST = ROOT / "scripts/ci_steps.json"


def step_id(step: dict[str, Any]) -> str:
    if step.get("name"):
        return str(step["name"])
    lines = [ln.strip() for ln in str(step["run"]).splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return lines[0]


def ci_steps(workflow: dict[str, Any]) -> dict[str, list[str]]:
    return {
        job: [step_id(s) for s in body.get("steps", []) if "run" in s]
        for job, body in workflow["jobs"].items()
        if any("run" in s for s in body.get("steps", []))
    }


def check(workflow: dict[str, Any], listed: dict[str, list[dict[str, str]]]) -> list[str]:
    """Pure: the problems between the workflow's steps and the list."""
    problems: list[str] = []
    actual = ci_steps(workflow)
    for job, steps in actual.items():
        entries = {e["step"]: e for e in listed.get(job, [])}
        for sid in steps:
            e = entries.get(sid)
            if e is None:
                problems.append(f"{job}: step {sid!r} has no twin or no_local_twin reason in scripts/ci_steps.json")
            elif not (e.get("twin") or e.get("no_local_twin")):
                problems.append(f"{job}: step {sid!r} is listed with neither a twin nor a no_local_twin reason")
    for job, entries in listed.items():
        if job not in actual:
            problems.append(f"{job}: listed, but ci.yml has no such job with run steps")
            continue
        for e in entries:
            if e["step"] not in actual[job]:
                problems.append(f"{job}: listed step {e['step']!r} is not in ci.yml")
    return problems


def load() -> tuple[dict[str, Any], dict[str, list[dict[str, str]]]]:
    return yaml.safe_load(WORKFLOW.read_text()), json.loads(LIST.read_text())["jobs"]


def commands(listed: dict[str, list[dict[str, str]]], only: str | None) -> list[tuple[str, str, str | None]]:
    """(job, command, None) for a twin, (job, step, reason) for a step with none; a command is listed once."""
    out: list[tuple[str, str, str | None]] = []
    seen: set[str] = set()
    for job, entries in listed.items():
        if only and job != only:
            continue
        for e in entries:
            if e.get("twin"):
                if e["twin"] not in seen:
                    seen.add(e["twin"])
                    out.append((job, e["twin"], None))
            else:
                out.append((job, e["step"], e.get("no_local_twin", "")))
    return out


def run(only: str | None, plan: bool) -> int:
    _, listed = load()
    if only and only not in listed:
        print(f"ci-local: no job {only!r}; jobs: {', '.join(listed)}")
        return 2
    failed: list[str] = []
    for job, cmd, reason in commands(listed, only):
        if reason is not None:
            print(f"[{job}] no local twin: {cmd[:50]} ({reason[:70]})")
        elif plan:
            print(f"[{job}] {cmd}")
        else:
            print(f"== [{job}] {cmd}", flush=True)
            if subprocess.run(["bash", "-c", cmd], cwd=ROOT, check=False).returncode != 0:
                failed.append(f"[{job}] {cmd}")
    if failed:
        print(f"ci-local: {len(failed)} failed:")
        print("\n".join(f"  - {f}" for f in failed))
        return 1
    if not plan:
        print("ci-local: every twin passed")
    return 0


def self_test() -> int:
    workflow, listed = load()
    assert check(workflow, listed) == [], check(workflow, listed)
    extra = {"jobs": {**workflow["jobs"], "planted": {"steps": [{"run": "echo planted"}]}}}
    unlisted = check(extra, listed)
    stale = check(workflow, {**listed, "docs": [*listed["docs"], {"step": "gone step", "twin": "true"}]})
    ok = any("echo planted" in p for p in unlisted) and any("gone step" in p for p in stale)
    print("planted unlisted step:", unlisted[:1])
    print("planted stale entry:", stale[:1])
    print("ci_steps self-test: " + ("ok, both refused" if ok else "FAILED, a planted miss was accepted"))
    return 0 if ok else 1


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    if "--run" in argv:
        job = argv[argv.index("--job") + 1] if "--job" in argv else None
        return run(job or None, "--plan" in argv)
    problems = check(*load())
    print("\n".join(problems) if problems else "ci steps: every ci.yml run step has a twin or a reason")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
