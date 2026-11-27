#!/usr/bin/env python3
"""The pull request flow's steps that run on GitHub Actions, each through `gh`. Stdlib only.

  verify --branch B     `make gha-verify`: start verify-full.yml on B, watch it, print each failed job's first error
  failures --run ID     each failed job of a run with its first error line
  ready                 ci.yml job `ready`: fails when the branch is behind develop, CodeQL is red or a job is red
  sync-prs [--only N]   keep-current.yml: merge develop into every open pull request behind it (never a rebase);
                        a conflict gets the label needs-merge and a comment naming the files
  queue-failure         queue-retry.yml: a failed merge queue run reruns its failed jobs once; a second failure
                        comments each failed job and its first error line; a green rerun queues the request again
  --self-test           every decision below on planted input

The decisions are pure functions (first_error, ready_reasons, to_sync, queue_step); the commands around them only read
and write GitHub. `--dry-run` on sync-prs and queue-failure prints what would be done and changes nothing.
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
LABEL = "needs-merge"
RED = ("failure", "cancelled", "timed_out")
STAMP = re.compile(r"^\S*\d{4}-\d\d-\d\dT[\d:.]+Z ?")
ERROR = re.compile(r"##\[error\]|^E  |\b(FAILED|ERROR|Error:|error:|Traceback)\b|make: \*\*\*")
QUEUE_BRANCH = re.compile(r"^gh-readonly-queue/[^/]+(?:/.+)?/pr-(\d+)-[0-9a-f]+$")


def first_error(log: str) -> str:
    """The first line of a job log that names the failure, without its timestamp; the last line when none does."""
    lines = [STAMP.sub("", raw.split("\t")[-1]).strip() for raw in log.splitlines()]
    lines = [ln for ln in lines if ln]
    # "Process completed with exit code 1" is the runner's own line and says nothing; an earlier line is the cause.
    named = [ln for ln in lines if ERROR.search(ln) and "Process completed with exit code" not in ln]
    line = named[0] if named else (lines[-1] if lines else "no log")
    return line.replace("##[error]", "").strip()[:300]


def ready_reasons(needs: dict[str, dict[str, str]], behind: int, codeql: dict[str, str]) -> list[str]:
    """Why a pull request is not ready for the queue; empty when it is."""
    reasons = [f"job {name} is {job.get('result')}" for name, job in sorted(needs.items()) if job.get("result") in RED]
    if behind > 0:
        reasons.append(
            f"the branch is {behind} commit(s) behind develop; keep-current.yml merges develop in, or update it"
        )
    reasons += [
        f"CodeQL {name} is {result}"
        for name, result in sorted(codeql.items())
        if result not in ("success", "neutral", "skipped")
    ]
    return reasons


def to_sync(prs: list[dict], behind: set[int]) -> list[int]:
    """The pull requests develop is merged into: open, not a draft, from this repository, behind, and not in the queue
    (a push to a queued pull request takes it out, and every queue merge moves develop). Dependabot keeps its own
    branches current and stops once another author pushes to one."""
    return [
        p["number"]
        for p in prs
        if p["number"] in behind
        and not p.get("isDraft")
        and not p.get("isCrossRepository")
        and not p.get("isInMergeQueue")
        and not str(p.get("headRefName", "")).startswith("dependabot/")
    ]


def queue_step(attempt: int, conclusion: str) -> str:
    """What a finished merge queue run asks for: rerun (first failure), comment (it failed again), requeue (the rerun
    passed, and the queue had already dropped the pull request), or nothing."""
    if conclusion in RED:
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
    jobs = json.loads(gh("run", "view", run, "--json", "jobs"))["jobs"]
    out = []
    for job in jobs:
        if job.get("conclusion") not in RED:
            continue
        log = gh("api", f"repos/{repo()}/actions/jobs/{job['databaseId']}/logs", check=False)
        out.append((job["name"], first_error(log) if log else f"{job['conclusion']}, no log"))
    return out


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
    sha, base, event = (
        os.environ.get("HEAD_SHA", ""),
        os.environ.get("BASE_REF", ""),
        os.environ.get("GITHUB_EVENT_NAME", ""),
    )
    behind, codeql = 0, {}
    # A queue group and a push are built on develop already, and CodeQL reports on pull requests (codeql.yml).
    if event == "pull_request" and sha:
        if base == "develop":
            behind = int(gh("api", f"repos/{repo()}/compare/develop...{sha}", "--jq", ".behind_by").strip() or 0)
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
    reasons = ready_reasons(needs, behind, codeql)
    for r in reasons:
        print(f"::error title=Not ready::{r}")
    print("ready: " + ("no, see above" if reasons else "every job passed, CodeQL is green, the branch holds develop"))
    return 1 if reasons else 0


def open_prs() -> list[dict]:
    owner, name = repo().split("/")
    q = (
        "query($o:String!,$n:String!){repository(owner:$o,name:$n){"
        'pullRequests(states:OPEN,baseRefName:"develop",first:100){nodes{'
        "number isDraft headRefName isCrossRepository isInMergeQueue labels(first:30){nodes{name}}}}}}"
    )
    return json.loads(gh("api", "graphql", "-f", f"query={q}", "-f", f"o={owner}", "-f", f"n={name}"))["data"][
        "repository"
    ]["pullRequests"]["nodes"]


def cmd_sync(only: int | None, dry: bool) -> int:
    prs = [p for p in open_prs() if only in (None, p["number"])]
    git("fetch", "-q", "origin", "+refs/heads/*:refs/remotes/origin/*")
    behind = {
        p["number"]
        for p in prs
        if git("merge-base", "--is-ancestor", "origin/develop", f"origin/{p['headRefName']}", check=False).returncode
        != 0
    }
    push_url = os.environ.get("PUSH_URL") or "origin"
    for p in prs:
        n, head = p["number"], p["headRefName"]
        labelled = LABEL in [x["name"] for x in p["labels"]["nodes"]]
        if n not in to_sync(prs, behind):
            continue
        if dry:
            print(f"#{n} {head}: would merge develop in")
            continue
        git("checkout", "-q", "--detach", f"origin/{head}")
        merge = git("merge", "--no-edit", "-m", f"Merge branch 'develop' into {head}", "origin/develop", check=False)
        if merge.returncode != 0:
            files = git("diff", "--name-only", "--diff-filter=U").stdout.split()
            git("merge", "--abort", check=False)
            print(f"#{n} {head}: conflicts in {' '.join(files)}")
            if not labelled:
                gh(
                    "label",
                    "create",
                    LABEL,
                    "--force",
                    "--color",
                    "B60205",
                    "--description",
                    "develop no longer merges cleanly into this branch",
                    check=False,
                )
                gh("pr", "edit", str(n), "--add-label", LABEL)
                gh(
                    "pr",
                    "comment",
                    str(n),
                    "--body",
                    "develop no longer merges into this branch. Conflicting files:\n\n"
                    + "\n".join(f"- `{f}`" for f in files)
                    + "\n\nMerge develop in by hand (`git merge origin/develop`, never a rebase) and push.",
                )
            continue
        pushed = git("push", "-q", push_url, f"HEAD:refs/heads/{head}", check=False)
        if pushed.returncode != 0:
            print(f"#{n} {head}: push refused: {pushed.stderr.strip()}")
            continue
        print(f"#{n} {head}: develop merged in")
        if labelled:
            gh("pr", "edit", str(n), "--remove-label", LABEL, check=False)
    return 0


def cmd_queue_failure(run: str, attempt: int, conclusion: str, *, branch: str, url: str, dry: bool) -> int:
    pr, step = queue_pr(branch), queue_step(attempt, conclusion)
    print(f"queue run {run} attempt {attempt} on {branch}: {conclusion}, so {step}" + (f" (#{pr})" if pr else ""))
    if dry or step == "nothing" or pr is None:
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
        "checks\tmake\t2026-11-26T10:00:00.1Z == sbom\n"
        "checks\tmake\t2026-11-26T10:00:01.1Z FAILED scripts/tests/test_x.py::test_y - AssertionError\n"
        "checks\tmake\t2026-11-26T10:00:02.1Z ##[error]Process completed with exit code 1.\n"
    )
    green = {"checks": {"result": "success"}, "docs": {"result": "skipped"}}
    prs = [
        {"number": 1, "isDraft": False, "isCrossRepository": False, "isInMergeQueue": False},
        {"number": 2, "isDraft": True, "isCrossRepository": False, "isInMergeQueue": False},
        {"number": 3, "isDraft": False, "isCrossRepository": True, "isInMergeQueue": False},
        {"number": 4, "isDraft": False, "isCrossRepository": False, "isInMergeQueue": True},
        {"number": 5, "isDraft": False, "isCrossRepository": False, "isInMergeQueue": False},
        {
            "number": 6,
            "isDraft": False,
            "isCrossRepository": False,
            "isInMergeQueue": False,
            "headRefName": "dependabot/npm/x",
        },
    ]
    cases = [
        (
            "the first error is the failing test, not the runner's exit line",
            first_error(log),
            "FAILED scripts/tests/test_x.py::test_y - AssertionError",
        ),
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
        ("a green, current pull request is ready", ready_reasons(green, 0, {"analyze python": "success"}), []),
        ("a branch behind develop is not ready", len(ready_reasons(green, 2, {"analyze python": "success"})), 1),
        (
            "a red CodeQL analysis is not ready",
            ready_reasons(green, 0, {"analyze python": "failure"}),
            ["CodeQL analyze python is failure"],
        ),
        (
            "a CodeQL analysis that never reported is not ready",
            len(ready_reasons(green, 0, {"analysis": "missing"})),
            1,
        ),
        (
            "a red or cancelled job is not ready",
            ready_reasons({"checks": {"result": "failure"}, "docs": {"result": "cancelled"}}, 0, {}),
            ["job checks is failure", "job docs is cancelled"],
        ),
        (
            "drafts, forks, queued, dependabot and current pull requests are left alone",
            to_sync(prs, {1, 2, 3, 4, 6}),
            [1],
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
    ap.add_argument("command", nargs="?", choices=["verify", "failures", "ready", "sync-prs", "queue-failure"])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--branch", default="")
    ap.add_argument("--run", default="")
    ap.add_argument("--attempt", type=int, default=1)
    ap.add_argument("--conclusion", default="failure")
    ap.add_argument("--url", default="")
    ap.add_argument("--only", type=int)
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
    if a.command == "sync-prs":
        return cmd_sync(a.only, a.dry_run)
    if a.command == "queue-failure":
        return cmd_queue_failure(a.run, a.attempt, a.conclusion, branch=a.branch, url=a.url, dry=a.dry_run)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
