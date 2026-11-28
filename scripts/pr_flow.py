#!/usr/bin/env python3
"""The pull request flow's steps that run on GitHub Actions, each through `gh`. Stdlib only.

  verify --branch B     `make gha-verify`: start verify-full.yml on B, watch it, print each failed job's first error
  failures --run ID     each failed job of a run with its first error line
  ready                 ci.yml job `ready`: fails when CodeQL is red or a job is red
  queue-failure         queue-retry.yml: a failed merge queue run reruns its failed jobs once; a second failure
                        comments each failed job and its first error line; a green rerun queues the request again
  --self-test           every decision below on planted input

The decisions are pure functions (first_error, ready_reasons, queue_step); the commands around them only read
and write GitHub. `--dry-run` on queue-failure prints what would be done and changes nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time

WORKFLOW = "verify-full.yml"
RED = ("failure", "cancelled", "timed_out")
STAMP = re.compile(r"^\S*\d{4}-\d\d-\d\dT[\d:.]+Z ?")
QUEUE_BRANCH = re.compile(r"^gh-readonly-queue/[^/]+(?:/.+)?/pr-(\d+)-[0-9a-f]+$")


def first_error(log: str) -> str:
    """The line of a failed step's log that names the failure, without its timestamp. A real log holds many lines that
    only look like errors (a self-test printing its planted failure, a command echoed with `grep FAILED` in it), so the
    order is: a pytest FAILED or ERROR line, the entry under `make checks`' own "check(s) failed:" list, a workflow
    annotation (a warning raised inside a passing test is annotated too, so it comes after), a pytest E line, make's own
    error, then the last line. The runner's "Process completed with exit code" says nothing."""
    lines = [STAMP.sub("", raw.split("\t")[-1]).rstrip() for raw in log.splitlines()]
    lines = [ln for ln in lines if ln.strip() and "Process completed with exit code" not in ln]
    listed = [lines[k + 1] for k, ln in enumerate(lines[:-1]) if "check(s) failed:" in ln]
    picks = (
        [ln for ln in lines if re.match(r"(FAILED|ERROR) \S+(::| - )", ln)],
        listed,
        [ln for ln in lines if "##[error]" in ln],
        [ln for ln in lines if ln.startswith("E   ")],
        [ln for ln in lines if ln.startswith("make: ***")],
        lines[-1:],
    )
    line = next((found[0] for found in picks if found), "no log")
    return line.replace("##[error]", "").strip(" -")[:300]


def ready_reasons(needs: dict[str, dict[str, str]], codeql: dict[str, str]) -> list[str]:
    """Why a pull request is not ready for the queue; empty when it is."""
    reasons = [f"job {name} is {job.get('result')}" for name, job in sorted(needs.items()) if job.get("result") in RED]
    reasons += [
        f"CodeQL {name} is {result}"
        for name, result in sorted(codeql.items())
        if result not in ("success", "neutral", "skipped")
    ]
    return reasons


def queue_step(attempt: int, conclusion: str) -> str:
    """What a finished merge queue run asks for: rerun (first failure), comment (it failed again), requeue (the rerun
    passed, and the queue had already dropped the pull request), or nothing."""
    # A cancelled run is the queue rebuilding its group, not a failure of this pull request.
    if conclusion in ("failure", "timed_out"):
        return "rerun" if attempt <= 1 else "comment"
    return "requeue" if conclusion == "success" and attempt > 1 else "nothing"


def queue_pr(branch: str) -> int | None:
    m = QUEUE_BRANCH.match(branch)
    return int(m.group(1)) if m else None


def failure_comment(failed: list[tuple[str, str]], url: str) -> str:
    rows = "\n".join(f"- `{name}`: {line}" for name, line in failed) or "- no failed job could be read"
    head = f"The merge queue run failed twice ({url}), so this pull request is out of the queue."
    return f"{head}\n\n{rows}\n\nFix it, then `make requeue PR=<n>`."


def gh(*args: str, check: bool = True, stdin: str | None = None) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, input=stdin, check=False)
    if check and r.returncode != 0:
        sys.exit(f"gh {' '.join(args[:4])}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


def git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=check)


def repo() -> str:
    return (
        os.environ.get("GITHUB_REPOSITORY")
        or gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner").strip()
    )


def failures(run: str) -> list[tuple[str, str]]:
    """Each failed job with the first error of its failed steps (`gh run view --log-failed`: job, step, line)."""
    jobs = json.loads(gh("run", "view", run, "--json", "jobs"))["jobs"]
    # ci-ok and ready only repeat that another job failed.
    red = [job["name"] for job in jobs if job.get("conclusion") in RED and job["name"] not in ("ci-ok", "ready")]
    logs: dict[str, list[str]] = {}
    for raw in gh("run", "view", run, "--log-failed", check=False).splitlines():
        logs.setdefault(raw.split("\t", 1)[0], []).append(raw)
    return [(name, first_error("\n".join(logs[name])) if name in logs else "no log of a failed step") for name in red]


def print_failures(run: str) -> int:
    failed = failures(run)
    for name, line in failed:
        print(f"{name}: {line}")
    return len(failed)


def cmd_verify(branch: str) -> int:
    before = {
        r["databaseId"]
        for r in json.loads(
            gh(
                "run",
                "list",
                "--workflow",
                WORKFLOW,
                "--branch",
                branch,
                "--event",
                "workflow_dispatch",
                "--json",
                "databaseId",
                "-L",
                "20",
            )
        )
    }
    gh("workflow", "run", WORKFLOW, "--ref", branch)
    run = ""
    for _ in range(30):
        time.sleep(4)
        runs = json.loads(
            gh(
                "run",
                "list",
                "--workflow",
                WORKFLOW,
                "--branch",
                branch,
                "--event",
                "workflow_dispatch",
                "--json",
                "databaseId,url",
                "-L",
                "20",
            )
        )
        new = [r for r in runs if r["databaseId"] not in before]
        if new:
            run = str(new[0]["databaseId"])
            print(f"gha-verify: {branch} runs at {new[0]['url']}", flush=True)
            break
    if not run:
        sys.exit(f"gha-verify: {WORKFLOW} was started on {branch} but no run appeared")
    green = (
        subprocess.run(
            ["gh", "run", "watch", run, "--exit-status", "--interval", "30"], stdout=subprocess.DEVNULL, check=False
        ).returncode
        == 0
    )
    if green:
        print(f"gha-verify: {branch} is green")
        return 0
    print(f"gha-verify: {branch} is red; the first error of each failed job:")
    print_failures(run)
    return 1


def cmd_ready() -> int:
    needs = json.loads(os.environ.get("NEEDS") or "{}")
    sha, event = os.environ.get("HEAD_SHA", ""), os.environ.get("GITHUB_EVENT_NAME", "")
    codeql = {}
    # The merge queue tests a pull request on develop's tip, so being behind develop is not checked here; CodeQL
    # reports on pull requests only (codeql.yml).
    if event == "pull_request" and sha:
        deadline = time.time() + int(os.environ.get("CODEQL_WAIT", "2400"))
        while True:
            runs = json.loads(
                gh(
                    "api",
                    f"repos/{repo()}/commits/{sha}/check-runs?per_page=100",
                    "--jq",
                    '[.check_runs[] | select(.name | startswith("analyze "))]',
                )
            )
            codeql = {r["name"]: (r["conclusion"] or r["status"]) for r in runs}
            if (runs and all(r["status"] == "completed" for r in runs)) or time.time() > deadline:
                break
            time.sleep(20)
        if not codeql:
            codeql = {"analysis": "missing"}
    reasons = ready_reasons(needs, codeql)
    for r in reasons:
        print(f"::error title=Not ready::{r}")
    print("ready: " + ("no, see above" if reasons else "every job passed, CodeQL is green"))
    return 1 if reasons else 0


def cmd_queue_failure(run: str, attempt: int, conclusion: str, *, branch: str, url: str, dry: bool) -> int:
    pr, step = queue_pr(branch), queue_step(attempt, conclusion)
    print(f"queue run {run} attempt {attempt} on {branch}: {conclusion}, so {step}" + (f" (#{pr})" if pr else ""))
    if dry or step == "nothing" or pr is None:
        return 0
    state = json.loads(gh("pr", "view", str(pr), "--json", "state,isDraft"))
    if state["state"] != "OPEN":
        print(f"#{pr} is {state['state']}; nothing to do")
        return 0
    if step == "rerun":
        gh("run", "rerun", run, "--failed")
    elif step == "comment":
        gh("pr", "comment", str(pr), "--body", failure_comment(failures(run), url))
    elif step == "requeue":
        gh("pr", "merge", str(pr), "--auto", "--merge")
    return 0


def self_test() -> int:
    log = (
        "checks\tmake\t2026-11-26T10:00:00.1Z == ci-local-self-test\n"
        "checks\tmake\t2026-11-26T10:00:00.2Z ci-local: 2 jobs run, 1 failed, 0 skipped {'x: red': 'failed'}\n"
        "checks\tmake\t2026-11-26T10:00:01.1Z verify: 1 check(s) failed:\n"
        "checks\tmake\t2026-11-26T10:00:01.2Z   - node scripts/changelog-check.mjs --entries (exit 1)\n"
        "checks\tmake\t2026-11-26T10:00:01.3Z make: *** [make/checks.mk:167: checks] Error 1\n"
        "checks\tmake\t2026-11-26T10:00:02.1Z ##[error]Process completed with exit code 2.\n"
    )
    pytest_log = (
        "j\ts\t2026-11-26T10:00:00Z grep -E ' (FAILED|ERROR)' log\n"
        "j\ts\t2026-11-26T10:00:01Z FAILED tests/test_x.py::test_y - boom"
    )
    noisy = (
        "j\ts\t2026-11-26T10:00:00Z ##[error]  raise RuntimeError('x')\nj\ts\t2026-11-26T10:00:01Z FAILED a.py::t - no"
    )
    green = {"checks": {"result": "success"}, "docs": {"result": "skipped"}}
    cases = [
        (
            "the failed check is named, not a self-test's planted failure or the runner's exit line",
            first_error(log),
            "node scripts/changelog-check.mjs --entries (exit 1)",
        ),
        (
            "a pytest failure is named, not the command that greps for one",
            first_error(pytest_log),
            "FAILED tests/test_x.py::test_y - boom",
        ),
        (
            "a failed test wins over an annotation raised inside a passing one",
            first_error(noisy),
            "FAILED a.py::t - no",
        ),
        ("a cancelled queue run is the queue regrouping, not a failure", queue_step(1, "cancelled"), "nothing"),
        (
            "a log with no error line gives its last line",
            first_error("a\tb\t2026-11-26T10:00:00Z one\na\tb\t2026-11-26T10:00:01Z two"),
            "two",
        ),
        (
            "an annotation loses its marker",
            first_error("j\ts\t2026-11-26T10:00:00Z ##[error]Staging not deployed"),
            "Staging not deployed",
        ),
        ("a green, current pull request is ready", ready_reasons(green, {"analyze python": "success"}), []),
        (
            "a red CodeQL analysis is not ready",
            ready_reasons(green, {"analyze python": "failure"}),
            ["CodeQL analyze python is failure"],
        ),
        (
            "a CodeQL analysis that never reported is not ready",
            len(ready_reasons(green, {"analysis": "missing"})),
            1,
        ),
        (
            "a red or cancelled job is not ready",
            ready_reasons({"checks": {"result": "failure"}, "docs": {"result": "cancelled"}}, {}),
            ["job checks is failure", "job docs is cancelled"],
        ),
        ("a first queue failure reruns the failed jobs", queue_step(1, "failure"), "rerun"),
        ("a second queue failure comments", queue_step(2, "failure"), "comment"),
        ("a green rerun queues the pull request again", queue_step(2, "success"), "requeue"),
        ("a green first run does nothing", queue_step(1, "success"), "nothing"),
        ("the queue branch names its pull request", queue_pr("gh-readonly-queue/develop/pr-266-0a1b2c3d"), 266),
        ("any other branch names none", queue_pr("fix/console-chat-card-links"), None),
        (
            "the comment lists each failed job with its line",
            "- `checks`: boom" in failure_comment([("checks", "boom")], "u"),
            True,
        ),
    ]
    bad = [f"{name}: got {got!r}, expected {want!r}" for name, got, want in cases if got != want]
    for b in bad:
        print(f"pr_flow self-test FAILED: {b}")
    if not bad:
        print(f"pr_flow self-test: {len(cases)} cases passed")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", choices=["verify", "failures", "ready", "queue-failure"])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--branch", default="")
    ap.add_argument("--run", default="")
    ap.add_argument("--attempt", type=int, default=1)
    ap.add_argument("--conclusion", default="failure")
    ap.add_argument("--url", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.command == "verify":
        return cmd_verify(a.branch or sys.exit("usage: pr_flow.py verify --branch <branch>"))
    if a.command == "failures":
        return 1 if print_failures(a.run or sys.exit("usage: pr_flow.py failures --run <id>")) else 0
    if a.command == "ready":
        return cmd_ready()
    if a.command == "queue-failure":
        return cmd_queue_failure(a.run, a.attempt, a.conclusion, branch=a.branch, url=a.url, dry=a.dry_run)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
