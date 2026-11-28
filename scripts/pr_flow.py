#!/usr/bin/env python3
"""The pull request flow's steps that run on GitHub Actions, each through `gh`. Stdlib only.

  verify --branch B     `make gha-verify`: start verify-full.yml on B, watch it, print each failed job's first error
  failures --run ID     each failed job of a run with its first error line
  ready                 ci.yml job `ready`: fails when CodeQL or a job is red; in the merge queue also when a pull
                        request of the group has no valid `reviewed` label (review_problems)
  queue-failure         queue-retry.yml: a failed merge queue run reruns its failed jobs once; a second failure
                        comments each failed job and its first error line; a green rerun queues the request again
  auto-queue --pr N     auto-queue.yml: arms or disarms the merge queue for one pull request into develop by its labels
                        (`reviewed` arms it, `hold` or a draft, a fork or a stacked base keeps it out); a push takes
                        `reviewed` off and disarms. A convenience: the queue's `ready` is what enforces the review
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
from collections.abc import Callable

WORKFLOW = "verify-full.yml"
RED = ("failure", "cancelled", "timed_out")
STAMP = re.compile(r"^\S*\d{4}-\d\d-\d\dT[\d:.]+Z ?")
WRITERS = ("admin", "maintain", "write")
WORKFLOW_AUTHOR = "github-actions[bot]"
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
        f"CodeQL {name} is {result}" for name, result in sorted(codeql.items()) if result not in ("success", "neutral")
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


def auto_queue_step(pr: dict) -> str:
    """What the kanban asks of one pull request: `arm`, `disarm` or `nothing`. Armed is ready for the merge queue: not
    a draft, labelled `reviewed` (the reviewer's label; approvals cannot be used, one account authors every pull
    request), without `hold`, into develop, from this repository. The release workflow arms its own merge-back."""
    if str(pr["head"]).startswith("merge-back/"):
        return "nothing"
    labels = set(pr["labels"])
    ok = (
        pr["base"] == "develop" and not pr["draft"] and not pr["fork"] and "reviewed" in labels and "hold" not in labels
    )
    if ok and not pr["armed"]:
        return "arm"
    return "disarm" if pr["armed"] and not ok else "nothing"


def failure_comment(failed: list[tuple[str, str]], url: str) -> str:
    rows = "\n".join(f"- `{name}`: {line}" for name, line in failed) or "- no failed job could be read"
    head = f"The merge queue run failed twice ({url}), so this pull request is out of the queue."
    return f"{head}\n\n{rows}\n\nFix it, then `make requeue PR=<n>`."


def gh(*args: str, check: bool = True, stdin: str | None = None) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True, input=stdin, check=False)
    if check and r.returncode != 0:
        sys.exit(f"gh {' '.join(args[:4])}: {r.stderr.strip() or r.stdout.strip()}")
    return r.stdout


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


def review_problems(pr: dict, events: list[dict], pushed_at: str, permission: Callable[[str], str]) -> list[str]:
    """Why a pull request into develop may not enter the merge queue; empty when it may. It needs a `reviewed` label
    that was given after its head was pushed (the last `labeled` or `unlabeled` event of that label decides), by
    someone with write access, and no `hold`. The merge-back that release-finish.yml opens (its author is the
    workflow's) is the one exemption. Times are the API's UTC `...Z` strings, which sort as text."""
    if "hold" in pr["labels"]:
        return ["it carries `hold`"]
    if pr["head"].startswith("merge-back/") and pr["author"] == WORKFLOW_AUTHOR and not pr["fork"]:
        return []
    marks = sorted(
        (e for e in events if e["event"] in ("labeled", "unlabeled") and e["label"] == "reviewed"),
        key=lambda e: e["at"],
    )
    last = marks[-1] if marks else None
    if last is None or last["event"] != "labeled" or "reviewed" not in pr["labels"]:
        return ["it has no `reviewed` label given by a person (or the label was taken off)"]
    out = []
    if last["at"] <= pushed_at:
        out.append(f"`reviewed` was given at {last['at']}, not after the head was pushed at {pushed_at}")
    access = permission(last["actor"])
    if access not in WRITERS:
        out.append(f"{last['actor']} gave `reviewed` with {access or 'no'} access, not write")
    return out


def permission_of(actor: str) -> str:
    done = subprocess.run(
        ["gh", "api", f"repos/{repo()}/collaborators/{actor}/permission", "--jq", ".permission"],
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip() if done.returncode == 0 else ""


def review_facts(number: int) -> tuple[dict, list[dict], str]:
    """One pull request's facts: the pull request, the timeline events that matter, and when its head was pushed. GitHub
    shows no push time, so it is the later of the newest force-push event on the timeline and the earliest check suite
    of the head commit (created by the push that brought the commit; a commit cannot be reviewed before it exists on
    GitHub). A commit's own dates are the pusher's to choose and are not read."""
    info = json.loads(gh("api", f"repos/{repo()}/pulls/{number}"))
    raw = gh(
        "api",
        "--paginate",
        f"repos/{repo()}/issues/{number}/timeline?per_page=100",
        "--jq",
        '[.[] | select(.event | IN("labeled","unlabeled","head_ref_force_pushed"))'
        ' | {event, label: (.label.name // ""), actor: (.actor.login // ""), at: .created_at}]',
    )
    events = [e for line in raw.splitlines() if line.strip() for e in json.loads(line)]
    suites = json.loads(
        gh(
            "api",
            f"repos/{repo()}/commits/{info['head']['sha']}/check-suites?per_page=100",
            "--jq",
            "[.check_suites[].created_at]",
        )
    )
    if not suites:
        raise ValueError(f"no check suite for the head of #{number}")
    pushed = max([min(suites), *(e["at"] for e in events if e["event"] == "head_ref_force_pushed")])
    pr = {
        "labels": [x["name"] for x in info["labels"]],
        "head": info["head"]["ref"],
        "author": info["user"]["login"],
        "fork": info["head"]["repo"] is None or info["head"]["repo"]["full_name"] != info["base"]["repo"]["full_name"],
    }
    return pr, events, pushed


def group_prs(head_ref: str, base_sha: str, head_sha: str) -> list[int]:
    """The pull requests of a merge queue group: the one the queue branch names and every `Merge pull request #n`
    commit between the group's base and head."""
    found = {n for n in [queue_pr(head_ref.removeprefix("refs/heads/"))] if n}
    lines = gh(
        "api", f"repos/{repo()}/compare/{base_sha}...{head_sha}", "--jq", '.commits[].commit.message | split("\n")[0]'
    )
    found |= {int(m.group(1)) for ln in lines.splitlines() if (m := re.match(r"Merge pull request #(\d+) ", ln))}
    return sorted(found)


def queue_review_reasons() -> list[str]:
    """In the queue's run, every pull request of the group must hold a valid review; a failure to read any of it fails.
    A pull request's own run cannot judge this: a label starts no run, so it would stay red until a push."""
    try:
        numbers = group_prs(
            os.environ.get("GROUP_REF", ""), os.environ.get("GROUP_BASE", ""), os.environ.get("GROUP_HEAD", "")
        )
        if not numbers:
            return ["no pull request found in the queue group"]
        reasons = []
        for n in numbers:
            pr, events, pushed = review_facts(n)
            reasons += [f"#{n}: {why}" for why in review_problems(pr, events, pushed, permission_of)]
        return reasons
    except (SystemExit, KeyError, ValueError, TypeError) as err:
        return [f"the review could not be checked ({err}); the queue run fails closed"]


def cmd_ready() -> int:
    needs = json.loads(os.environ.get("NEEDS") or "{}")
    sha, event = os.environ.get("HEAD_SHA", ""), os.environ.get("GITHUB_EVENT_NAME", "")
    codeql = {}
    # The merge queue tests a pull request on develop's tip, so a stale base is not checked here; CodeQL
    # reports on pull requests only (codeql.yml). A pull request that changes no file runs no CodeQL (TRIVIAL).
    if event == "pull_request" and sha and os.environ.get("TRIVIAL") != "true":
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
    if event == "merge_group":
        reasons += queue_review_reasons()
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
        gh("pr", "edit", str(pr), "--add-label", "queue-failed")
    elif step == "requeue":
        gh("pr", "merge", str(pr), "--auto", "--merge")
    return 0


def gh_ok(*args: str) -> bool:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=False).returncode == 0


def drop_review(number: int, dry: bool) -> int:
    """Any push after the review takes `reviewed` off and disarms auto-merge, with no exception for a merge of develop.
    The label comes off first and the disarm is tried whatever happened to it; a failure of either fails the job, so a
    pull request is never left armed by a run that could not tell."""
    print(f"#{number}: a push, so `reviewed` comes off and auto-merge is disarmed")
    if dry:
        return 0
    removed = gh_ok("pr", "edit", str(number), "--remove-label", "reviewed")
    disarmed = gh_ok("pr", "merge", str(number), "--disable-auto") or not armed(number)
    if not (removed and disarmed):
        print(f"::error title=Review not dropped::#{number}: could not remove `reviewed` or disarm; do it by hand")
        return 1
    return 0


def armed(number: int) -> bool:
    """Whether auto-merge is on; an unreadable answer counts as on."""
    out = subprocess.run(
        ["gh", "api", f"repos/{repo()}/pulls/{number}", "--jq", ".auto_merge != null"],
        capture_output=True,
        text=True,
        check=False,
    )
    return out.returncode != 0 or out.stdout.strip() == "true"


def label_refused(number: int, actor: str, dry: bool) -> int | None:
    """`reviewed` counts only from someone with write, maintain or admin rights. None when the label stands; otherwise
    the label comes off with one comment and the answer is the exit code (1 when the removal failed)."""
    if permission_of(actor) in WRITERS:
        return None
    print(f"#{number}: {actor} may not label a pull request `reviewed`")
    if dry:
        return 0
    removed = gh_ok("pr", "edit", str(number), "--remove-label", "reviewed")
    gh_ok(
        "pr",
        "comment",
        str(number),
        "--body",
        "`reviewed` comes from a maintainer with write access; the label was removed.",
    )
    return 0 if removed else 1


def cmd_auto_queue(number: int, action: str, dry: bool, *, label: str = "", actor: str = "") -> int:
    """Only the API is called with the event's pull request number, never the pull request's code. `action` is
    empty for a hand-started run, which judges a pull request into develop and leaves every other base alone."""
    if action == "synchronize":
        # The merge-back that release-finish.yml arms is pushed to once, by the workflow, and is exempt from review.
        head = subprocess.run(
            ["gh", "api", f"repos/{repo()}/pulls/{number}", "--jq", ".head.ref"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        if head.startswith("merge-back/"):
            print(f"#{number}: a merge-back, left armed")
            return 0
        return drop_review(number, dry)
    info = json.loads(gh("api", f"repos/{repo()}/pulls/{number}"))
    if not action and info["base"]["ref"] != "develop":
        print(f"#{number}: base {info['base']['ref']}, not judged by hand")
        return 0
    labels = [x["name"] for x in info["labels"]]
    if action == "labeled" and label == "reviewed" and "reviewed" in labels:
        refused = label_refused(number, actor, dry)
        if refused is not None:
            return refused
    pr = {
        "base": info["base"]["ref"],
        "head": info["head"]["ref"],
        "draft": info["draft"],
        "fork": info["head"]["repo"] is None or info["head"]["repo"]["full_name"] != info["base"]["repo"]["full_name"],
        "labels": labels,
        "armed": info.get("auto_merge") is not None,
    }
    step = auto_queue_step(pr)
    print(f"#{number}: {step}")
    if dry or step == "nothing":
        return 0
    if step == "arm":
        gh("pr", "merge", str(number), "--auto", "--merge")
        if "queue-failed" in labels:
            gh("pr", "edit", str(number), "--remove-label", "queue-failed", check=False)
    else:
        gh("pr", "merge", str(number), "--disable-auto")
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
    base = {"base": "develop", "head": "fix/x", "draft": False, "fork": False, "labels": ["reviewed"], "armed": False}
    cases += [
        (
            "a reviewed, ready pull request into develop is armed; hold, draft, fork, stacked base, no label are not",
            [
                auto_queue_step(base),
                auto_queue_step({**base, "labels": ["reviewed", "hold"]}),
                auto_queue_step({**base, "draft": True}),
                auto_queue_step({**base, "fork": True}),
                auto_queue_step({**base, "base": "feat/y"}),
                auto_queue_step({**base, "labels": []}),
            ],
            ["arm", "nothing", "nothing", "nothing", "nothing", "nothing"],
        ),
        (
            "an armed pull request that loses its label, goes draft or gets `hold` is disarmed; a merge-back is not",
            [
                auto_queue_step({**base, "armed": True, "labels": []}),
                auto_queue_step({**base, "armed": True, "draft": True}),
                auto_queue_step({**base, "armed": True, "labels": ["reviewed", "hold"]}),
                auto_queue_step({**base, "armed": True}),
                auto_queue_step({**base, "head": "merge-back/release-1.2.1", "labels": [], "armed": True}),
            ],
            ["disarm", "disarm", "disarm", "nothing", "nothing"],
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
    ap.add_argument("command", nargs="?", choices=["verify", "failures", "ready", "queue-failure", "auto-queue"])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--branch", default="")
    ap.add_argument("--run", default="")
    ap.add_argument("--attempt", type=int, default=1)
    ap.add_argument("--conclusion", default="failure")
    ap.add_argument("--url", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pr", type=int, default=0)
    ap.add_argument("--action", default="")
    ap.add_argument("--label", default="")
    ap.add_argument("--actor", default="")
    a = ap.parse_args()
    if a.self_test:
        return self_test()
    if a.command == "verify":
        return cmd_verify(a.branch or sys.exit("usage: pr_flow.py verify --branch <branch>"))
    if a.command == "failures":
        return 1 if print_failures(a.run or sys.exit("usage: pr_flow.py failures --run <id>")) else 0
    if a.command == "ready":
        return cmd_ready()
    if a.command == "auto-queue":
        return cmd_auto_queue(
            a.pr or sys.exit("usage: pr_flow.py auto-queue --pr N"), a.action, a.dry_run, label=a.label, actor=a.actor
        )
    if a.command == "queue-failure":
        return cmd_queue_failure(a.run, a.attempt, a.conclusion, branch=a.branch, url=a.url, dry=a.dry_run)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
