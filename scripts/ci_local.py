#!/usr/bin/env python3
"""`make ci-local`: the jobs CI would run for this change, run here side by side, with one summary at the end.

  ci_local.py [--base REF] [--jobs N] [--job NAME] [--plan] [--full]
  ci_local.py --self-test

The job list is not copied from anywhere: scripts/ci-plan.sh prints the plan CI's `plan` job prints, each job's `if:`
in .github/workflows/ci.yml is evaluated against it, and a matrix job takes its entries from the plan's JSON the way
`fromJSON(needs.plan.outputs.<key>)` does. A matrix job runs the step's own `run:` text with the matrix values
substituted; every other job runs the local twins listed in scripts/ci_steps.json (which `ci_steps.py --check` keeps in
step with ci.yml). A job with no twin (SQL Server, release proof, the maintainer review) is listed as skipped, with why.

Each job gets its own test database (OPS_TEST_DATABASE_URL plus a suffix, made from the migrated template by
scripts/test_db.py) and its own service ports (the stack's ports plus 100 per job slot), so two jobs never share rows,
locks or a listener. Logs go to .run/ci-local/<time>/<job>.log. Exit 1 when any job failed.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import ci_steps

ROOT = Path(__file__).resolve().parents[1]
# Jobs that are not checks of the change: the plan itself, the join, and the deploy that follows a green push.
NOT_CHECKS = ("plan", "ci-ok", "staging")
# Ports of the shared infrastructure, which every job reaches; the rest are service ports a test may bind.
SHARED_PORTS = re.compile(r"^OPS_(PG|OPA|GREENMAIL_.*|MAILPIT_.*)_?PORT$|^OPS_PORT_OFFSET$")
# Long suites first, so the run does not end waiting on one of them alone (as VERIFY_POOL does in make/python.mk).
HEAVY = ("repo", "agents-service", "tools-service", "platform-service")


@dataclass
class Job:
    name: str  # the ci.yml job
    label: str  # the table row: the job, and its matrix entry
    commands: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    skipped: str = ""


@dataclass
class Result:
    job: Job
    status: str  # passed | failed | skipped
    seconds: float = 0.0
    log: str = ""


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def parse_plan(text: str) -> dict[str, str]:
    return dict(ln.split("=", 1) for ln in text.splitlines() if "=" in ln)


def condition(expr: str | None, plan: dict[str, str]) -> bool | None:
    """`if:` of a job or step against the plan outputs; None when it reads GitHub's own context (an event, a ref)."""
    if expr is None:
        return True
    text = str(expr).strip()
    text = re.sub(r"^\$\{\{(.*)\}\}$", r"\1", text, flags=re.S).strip()
    if re.search(r"\b(github|matrix|secrets|always|cancelled)\b", text):
        return None
    py = re.sub(r"needs\.plan\.outputs\.(\w+)", r"O['\1']", text).replace("&&", " and ").replace("||", " or ")
    # The text is this repo's own ci.yml; only plan lookups, string literals, comparisons and and/or may reach eval.
    if not re.fullmatch(r"(?:O\['\w+'\]|'[^']*'|[=!]=|\band\b|\bor\b|[()\s])+", py):
        raise ValueError(f"ci-local cannot read the condition {text!r}")
    return bool(eval(py, {"__builtins__": {}}, {"O": plan}))


def substitute(text: str, matrix: dict[str, Any]) -> str:
    return re.sub(r"\$\{\{\s*matrix\.(\w+)\s*\}\}", lambda m: str(matrix[m.group(1)]), text)


def matrix_entries(job: dict[str, Any], plan: dict[str, str]) -> list[dict[str, Any]] | None:
    """The job's matrix as CI expands it, or None for a job with none."""
    matrix = (job.get("strategy") or {}).get("matrix")
    if not matrix:
        return None
    for key, value in matrix.items():
        m = re.search(r"fromJSON\(needs\.plan\.outputs\.(\w+)\)", str(value))
        if m:
            entries = json.loads(plan[m.group(1)])
            return entries if key == "include" else [{key: e} for e in entries]
    return None


def step_ids(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {ci_steps.step_id(s): s for s in job.get("steps", []) if "run" in s}


def build_jobs(workflow: dict[str, Any], listed: dict[str, Any], plan: dict[str, str], only: str | None) -> list[Job]:
    jobs: list[Job] = []
    for name, body in workflow["jobs"].items():
        if name in NOT_CHECKS or (only and name != only):
            continue
        planned = condition(body.get("if"), plan)
        if planned is False:
            continue
        if planned is None:
            jobs.append(
                Job(name, name, skipped="its condition reads GitHub's event or branch, which a local run has not")
            )
            continue
        entries = matrix_entries(body, plan)
        steps = step_ids(body)
        if entries is not None:
            for entry in entries:
                label = f"{name}: " + " ".join(str(v) for v in entry.values())
                job = Job(name, label)
                for step in steps.values():
                    job.commands.append(substitute(str(step["run"]), entry))
                    job.env.update({k: substitute(str(v), entry) for k, v in (step.get("env") or {}).items()})
                jobs.append(job)
            continue
        job = Job(name, name)
        notes: list[str] = []
        for entry in listed.get(name, []):
            step = steps.get(entry["step"])
            if step is not None and condition(step.get("if"), plan) is False:
                continue
            if entry.get("twin"):
                if entry["twin"] not in job.commands:
                    job.commands.append(entry["twin"])
            else:
                notes.append(entry.get("no_local_twin", ""))
        if not job.commands:
            job.skipped = notes[0] if notes else "no local twin"
        jobs.append(job)
    return sorted(jobs, key=lambda j: (not any(h in j.label for h in HEAVY), j.skipped != ""))


def job_env(job: Job, slot: int, base_env: dict[str, str], base_sha: str) -> dict[str, str]:
    env = {**base_env, **job.env, "BASE_SHA": base_sha, "CI": "true"}
    # Its own database, named as make/env.mk names a run's so the sweep (scripts/scratch_db_sweep.py) drops it later.
    if env.get("OPS_TEST_DATABASE_URL"):
        env["OPS_TEST_DATABASE_URL"] = f"{env['OPS_TEST_DATABASE_URL']}_{slug(job.label)[:24]}"
    for var, value in base_env.items():
        if re.fullmatch(r"OPS_\w+_PORT", var) and not SHARED_PORTS.match(var) and value.isdigit():
            env[var] = str(int(value) + 100 * (slot + 1))
    return env


def run_job(
    job: Job, slot: int, logdir: Path, base_env: dict[str, str], base_sha: str, *, children: set[int]
) -> Result:
    if job.skipped:
        return Result(job, "skipped")
    log = logdir / f"{slug(job.label)}.log"
    script = "set -euo pipefail\n" + "\n".join(job.commands)
    started = time.monotonic()
    with log.open("w") as out:
        proc = subprocess.Popen(
            ["bash", "-c", script],
            cwd=ROOT,
            env=job_env(job, slot, base_env, base_sha),
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        children.add(proc.pid)
        code = proc.wait()
        children.discard(proc.pid)
    return Result(
        job,
        "passed" if code == 0 else "failed",
        time.monotonic() - started,
        str(log.relative_to(ROOT) if log.is_relative_to(ROOT) else log),
    )


def run_all(jobs: list[Job], width: int, logdir: Path, base_sha: str) -> list[Result]:
    logdir.mkdir(parents=True, exist_ok=True)
    runnable = [j for j in jobs if not j.skipped]
    children: set[int] = set()
    slots = {id(j): i for i, j in enumerate(runnable)}
    try:
        with ThreadPoolExecutor(max_workers=max(1, width)) as pool:
            futures = {
                id(j): pool.submit(
                    run_job, j, slots.get(id(j), 0), logdir, dict(os.environ), base_sha, children=children
                )
                for j in jobs
            }
            return [futures[id(j)].result() for j in jobs]
    except KeyboardInterrupt:
        for pid in children:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(pid, signal.SIGTERM)
        raise


def table(results: list[Result], wall: float) -> str:
    rows = [("job", "result", "seconds", "log")]
    for r in results:
        rows.append(
            (r.job.label, r.status, f"{r.seconds:.0f}" if r.status != "skipped" else "-", r.log or r.job.skipped[:60])
        )
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    fmt = "| " + " | ".join(f"{{:<{w}}}" for w in widths) + " |"
    lines = [
        fmt.format(*rows[0]),
        "|" + "|".join("-" * (w + 2) for w in widths) + "|",
        *(fmt.format(*r) for r in rows[1:]),
    ]
    failed = sum(r.status == "failed" for r in results)
    ran = sum(r.status != "skipped" for r in results)
    lines.append(f"\nci-local: {ran} jobs run, {failed} failed, {len(results) - ran} skipped, wall time {wall:.0f}s")
    return "\n".join(lines)


def tail(path: str, n: int = 15) -> str:
    try:
        return "\n".join((ROOT / path).read_text(errors="replace").splitlines()[-n:])
    except OSError:
        return ""


def main(argv: list[str]) -> int:
    if "--self-test" in argv:
        return self_test()
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/develop")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    ap.add_argument("--job")
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--full", action="store_true")
    args = ap.parse_args(argv)

    base = subprocess.run(
        ["git", "merge-base", args.base, "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    env = {**os.environ, **({"CI_FULL": "true"} if args.full else {})}
    plan_text = subprocess.run(
        ["bash", "scripts/ci-plan.sh", base], cwd=ROOT, env=env, capture_output=True, text=True, check=True
    ).stdout
    plan = parse_plan(plan_text)
    workflow, listed = ci_steps.load()
    jobs = build_jobs(workflow, listed, plan, args.job)
    print(f"ci-local: plan from {args.base} ({base[:9]}): full={plan['full']} services={plan['services']}")
    if args.plan:
        for j in jobs:
            print(f"[{j.label}]" + (f" skipped: {j.skipped}" if j.skipped else ""))
            for c in j.commands:
                print("   " + c.strip().replace("\n", "\n   "))
        return 0
    logdir = ROOT / ".run/ci-local" / time.strftime("%Y%m%d-%H%M%S")
    started = time.monotonic()
    results = run_all(jobs, args.jobs, logdir, base)
    print(table(results, time.monotonic() - started))
    for r in results:
        if r.status == "failed":
            print(f"\n--- {r.job.label}: last lines of {r.log}\n{tail(r.log)}")
    return 1 if any(r.status == "failed" for r in results) else 0


def self_test() -> int:
    plan = {
        "full": "false",
        "code": "true",
        "scripts": "false",
        "release": "false",
        "console": "false",
        "docs": "false",
        "mssql": "false",
        "repo_pool": "",
        "services": '["a-service"]',
        "packages": '["p"]',
        "service_jobs": '[{"service":"a-service","part":"verify"},{"service":"b-service","part":"test 1/2"}]',
    }
    cond = condition
    ok = [
        cond("needs.plan.outputs.code == 'true'", plan) is True,
        cond("needs.plan.outputs.console == 'true'", plan) is False,
        cond(
            "(needs.plan.outputs.full != 'true' && needs.plan.outputs.code == 'true')"
            " || needs.plan.outputs.release == 'true'",
            plan,
        )
        is True,
        cond("github.event_name == 'pull_request'", plan) is None,
    ]
    workflow, listed = ci_steps.load()
    jobs = build_jobs(workflow, listed, plan, None)
    labels = [j.label for j in jobs]
    ok += [
        "service: a-service verify" in labels and "service: b-service test 1/2" in labels,
        "package: p" in labels,
        "console" not in labels,  # the plan did not enable it
        all(j.skipped for j in jobs if j.name in ("release-proof", "maintainer-review")),
    ]
    print("plan to jobs:", labels)
    # A failing job must fail the run, and a passing one must not hide it: plant one of each.
    with tempfile.TemporaryDirectory() as tmp:
        planted = [Job("x", "x: green", commands=["true"]), Job("x", "x: red", commands=["echo boom; false"])]
        results = run_all(planted, 2, Path(tmp), "HEAD")
        by = {r.job.label: r.status for r in results}
        print(table(results, 0).splitlines()[-1], by)
        ok.append(by == {"x: green": "passed", "x: red": "failed"})
    print("ci_local self-test: " + ("ok, the red job was reported red" if all(ok) else f"FAILED {ok}"))
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
