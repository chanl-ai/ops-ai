"""`make release-intake` (scripts/release.py intake) and the report `make ci-local OUT=` writes, on a scratch origin
with a fake `gh` and a fake `make`; never the real remote.

Failure modes: a mechanical conflict (generated openapi, a list file, two migration heads) is resolved and its pull
request merged with its own merge commit; a logic conflict aborts only that pull request, merges the others and exits 2;
a red ci-local job blocks the push and lands in the report with its failing test ids; a rerun runs only the jobs the
earlier report marked red; a dry run changes nothing on the remote; a pull request GitHub will not retarget (already in
the train, queued, dependabot, draft) is skipped and the run still ends green."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parents[1]
TRAIN = "release/1.1.0"

FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
path = os.environ["FAKE_GH"]
state = json.load(open(path))
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write("gh " + " ".join(args) + chr(10))
if args[:2] == ["pr", "list"] and "--head" in args:
    print(json.dumps(state.get("release_prs", [])))
elif args[:2] == ["pr", "list"]:
    print(json.dumps(state["prs"]))
elif args[:3] == ["api", "-X", "PATCH"] and any(a.startswith("base=") for a in args):
    number = args[3].rsplit("/", 1)[1]
    if number in state.get("refuse", {}):
        sys.exit(state["refuse"][number])
    for pr in state["prs"]:
        if str(pr["number"]) == number:
            pr["baseRefName"] = [a for a in args if a.startswith("base=")][0][5:]
    json.dump(state, open(path, "w"))
elif args[:3] == ["api", "-X", "PATCH"]:
    pass
elif args[:2] == ["run", "list"]:
    print(json.dumps(state.get("runs", [])))
elif args[:2] == ["run", "cancel"]:
    pass
else:
    sys.exit("fake gh: unexpected " + " ".join(args))
"""

# `make -C <dir> ci-local ... OUT=<file> [RERUN=<file>]` copies a canned report; `openapi` writes the regenerated file.
FAKE_MAKE = """#!/bin/sh
echo "make $*" >> "$FAKE_LOG"
dir=$2
case "$3" in
  openapi) printf '{"v": "regenerated"}\\n' > "$dir/services/x/openapi.json" ;;
  ci-local)
    for a in "$@"; do case "$a" in OUT=*) out=${a#OUT=} ;; RERUN=*) rerun=1 ;; esac; done
    if [ -n "$rerun" ] && [ -f "$FAKE_CI_RERUN" ]; then cp "$FAKE_CI_RERUN" "$out"; exit 0; fi
    cp "$FAKE_CI" "$out"; exit "${FAKE_CI_RC:-0}" ;;
esac
exit 0
"""

GREEN: dict[str, Any] = {"summary": {"passed": 2, "failed": 0, "skipped": 0}, "jobs": []}
RED = {
    "summary": {"passed": 1, "failed": 1, "skipped": 0},
    "jobs": [
        {
            "label": "service: a-service test 1/2",
            "job": "service",
            "status": "failed",
            "log": ".run/ci-local/x/service_a.log",
            "failing_tests": ["services/a/tests/test_x.py::test_y"],
            "tail": "assert 1 == 2",
        }
    ],
}

IDENT = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, **IDENT}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout


MIGRATION = 'revision = "{rev}"\ndown_revision = {down}\n'


def scratch(tmp: Path) -> Path:
    """An origin whose develop and train hold the same first commit, and a clone of it."""
    remote, work = tmp / "remote.git", tmp / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True, capture_output=True)
    files = {
        "roadmap.json": json.dumps([{"title": "base"}], indent=2) + "\n",
        "services/x/openapi.json": '{"v": 0}\n',
        "services/x/migrations/versions/0001.py": MIGRATION.format(rev="0001", down="None"),
        "app.txt": "one\ntwo\nthree\n",
    }
    for name, text in files.items():
        (work / name).parent.mkdir(parents=True, exist_ok=True)
        (work / name).write_text(text)
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "first")
    git(work, "push", "-q", "origin", "HEAD:main", "HEAD:develop", f"HEAD:{TRAIN}")
    return work


def branch(work: Path, name: str, files: dict[str, str]) -> None:
    git(work, "checkout", "-q", "-b", name, "origin/develop")
    for path, text in files.items():
        (work / path).parent.mkdir(parents=True, exist_ok=True)
        (work / path).write_text(text)
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", f"feat: {name}")
    git(work, "push", "-q", "origin", name)
    git(work, "checkout", "-q", "--detach", "origin/develop")


def pr(number: int, head: str, **extra: Any) -> dict[str, Any]:
    return {
        "number": number,
        "headRefName": head,
        "baseRefName": "develop",
        "isDraft": False,
        "title": f"title of {head}",
        "createdAt": f"2026-11-{number:02d}T00:00:00Z",
        **extra,
    }


def intake(work: Path, tmp: Path, state: dict[str, Any], ci: dict[str, Any] = GREEN, **env: str) -> dict[str, Any]:
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, text in (("gh", FAKE_GH), ("make", FAKE_MAKE)):
        (bin_dir / name).write_text(text)
        (bin_dir / name).chmod(0o755)
    (tmp / "gh.json").write_text(json.dumps(state))
    (tmp / "ci.json").write_text(json.dumps(ci))
    full = {
        **os.environ,
        **IDENT,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_GH": str(tmp / "gh.json"),
        "FAKE_LOG": str(tmp / "calls.log"),
        "FAKE_CI": str(tmp / "ci.json"),
        "DRY": "0",
        "TRAIN": TRAIN,
        "INTAKE_DIR": str(tmp / "intake"),
        "INTAKE_SETUP": "true",
        "REPORT": str(tmp / "report.json"),
        **env,
    }
    done = subprocess.run(
        [sys.executable, str(SCRIPTS / "release.py"), "intake"],
        cwd=work,
        capture_output=True,
        text=True,
        env=full,
        check=False,
    )
    report = tmp / "report.json"
    out: dict[str, Any] = json.loads(report.read_text()) if report.exists() else {}
    out["code"], out["stdout"], out["stderr"] = done.returncode, done.stdout, done.stderr
    return out


def calls(tmp: Path) -> str:
    log = tmp / "calls.log"
    return log.read_text() if log.exists() else ""


def remote_sha(tmp: Path, ref: str) -> str:
    return git(tmp / "remote.git", "rev-parse", ref).strip()


def test_mechanical_conflicts_resolve_and_each_pull_request_gets_its_own_merge_commit(tmp_path: Path) -> None:
    work = scratch(tmp_path)
    for name, down in (("a", "0001"), ("b", "0001")):
        branch(
            work,
            f"feat/{name}",
            {
                "services/x/openapi.json": f'{{"v": "{name}"}}\n',
                "roadmap.json": json.dumps([{"title": "base"}, {"title": name}], indent=2) + "\n",
                f"services/x/migrations/versions/0002{name}.py": MIGRATION.format(rev=f"0002{name}", down=f'"{down}"'),
            },
        )
    out = intake(work, tmp_path, {"prs": [pr(1, "feat/a"), pr(2, "feat/b")]})
    assert out["code"] == 0, out["stderr"] + out["stdout"]
    assert [m["pr"] for m in out["merged"]] == [1, 2] and not out["conflicts"]
    head = remote_sha(tmp_path, TRAIN)
    assert head == out["head"] and out["push"] == "pushed"
    merges = git(tmp_path / "remote.git", "log", "--first-parent", "--merges", "--format=%s", TRAIN).split("\n")
    assert [m for m in merges if m] == [
        "Merge pull request #2 from origin/feat/b",
        "Merge pull request #1 from origin/feat/a",
    ]

    def show(path: str) -> str:
        return git(tmp_path / "remote.git", "show", f"{TRAIN}:{path}")

    assert [e["title"] for e in json.loads(show("roadmap.json"))] == ["base", "a", "b"]
    assert json.loads(show("services/x/openapi.json")) == {"v": "regenerated"}
    assert 'down_revision = "0002a"' in show("services/x/migrations/versions/0002b.py")
    assert "base=release/1.1.0" in calls(tmp_path) and not out["worktree"]


def test_a_logic_conflict_aborts_only_that_pull_request_and_exits_2(tmp_path: Path) -> None:
    work = scratch(tmp_path)
    branch(work, "feat/first", {"app.txt": "one\nfirst\nthree\n"})
    branch(work, "feat/clash", {"app.txt": "one\nclash\nthree\n"})
    branch(work, "feat/other", {"other.txt": "other\n"})
    state = {"prs": [pr(1, "feat/first"), pr(2, "feat/clash"), pr(3, "feat/other")]}
    out = intake(work, tmp_path, state)
    assert out["code"] == 2
    assert [m["pr"] for m in out["merged"]] == [1, 3]
    assert [(c["pr"], c["files"]) for c in out["conflicts"]] == [(2, ["app.txt"])]
    assert out["push"] == "pushed"  # the green part of the train is not held back by the one conflict
    assert git(tmp_path / "remote.git", "show", f"{TRAIN}:other.txt") == "other\n"
    left = Path(out["worktree"])
    assert left.exists() and git(left, "status", "--porcelain") == ""  # aborted, clean, ready for a person


def test_a_red_job_blocks_the_push_and_is_reported_with_its_test_ids_then_rerun_pushes(tmp_path: Path) -> None:
    work = scratch(tmp_path)
    branch(work, "feat/a", {"a.txt": "a\n"})
    before = remote_sha(tmp_path, TRAIN)
    out = intake(work, tmp_path, {"prs": [pr(1, "feat/a")]}, ci=RED, FAKE_CI_RC="1")
    assert out["code"] == 1 and out["push"] == "not pushed: ci-local is red"
    assert remote_sha(tmp_path, TRAIN) == before
    assert out["red"][0]["tests"] == ["services/a/tests/test_x.py::test_y"] and out["red"][0]["tail"] == "assert 1 == 2"
    # The fix is committed in the worktree the report names; RERUN then proves only the red job and pushes.
    wt = Path(out["worktree"])
    (wt / "fix.txt").write_text("fix\n")
    git(wt, "add", ".")
    git(wt, "commit", "-q", "-m", "fix: the test")
    (tmp_path / "rerun.json").write_text(json.dumps(GREEN))
    again = intake(
        work, tmp_path, {"prs": []}, RERUN=str(tmp_path / "report.json"), FAKE_CI_RERUN=str(tmp_path / "rerun.json")
    )
    assert again["code"] == 0 and again["push"] == "pushed" and remote_sha(tmp_path, TRAIN) == again["head"]
    assert f"RERUN={tmp_path / 'ci-local.json'}" in calls(tmp_path) and not again["worktree"]


def test_rerun_runs_only_the_jobs_the_earlier_report_marked_red(tmp_path: Path) -> None:
    earlier = {
        "jobs": [
            {"label": "checks", "job": "checks", "status": "passed", "seconds": 5, "log": "l", "skipped": ""},
            {"label": "usecase: uc-1:api", "job": "usecase", "status": "failed", "seconds": 1, "log": "l"},
            {"label": "usecase: uc-2", "job": "usecase", "status": "passed", "seconds": 1, "log": "l"},
        ]
    }
    (tmp_path / "earlier.json").write_text(json.dumps(earlier))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "make").write_text(
        '#!/bin/sh\necho "make $*" >> "$FAKE_LOG"\necho "FAILED tests/t.py::test_x - boom"\nexit 1\n'
    )
    (bin_dir / "make").chmod(0o755)
    # A release or hotfix branch's CI run plans every job, which asks make for the pool; this test is about the rerun.
    plain = {k: v for k, v in os.environ.items() if k not in ("GITHUB_REF", "CI_FULL")}
    env = {**plain, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_LOG": str(tmp_path / "calls.log")}
    done = subprocess.run(
        [sys.executable, str(SCRIPTS / "ci_local.py"), "--base", "HEAD", "--rerun", str(tmp_path / "earlier.json"),
         "--out", str(tmp_path / "now.json")],
        capture_output=True, text=True, env=env, check=False,
    )  # fmt: skip
    assert done.returncode == 1, done.stdout + done.stderr
    assert calls(tmp_path).strip() == "make -s usecase-test UC=uc-1 LAYER=api"  # nothing else ran
    now = {j["label"]: j for j in json.loads((tmp_path / "now.json").read_text())["jobs"]}
    assert now["usecase: uc-1:api"]["failing_tests"] == ["tests/t.py::test_x"]
    assert now["checks"]["carried"] and now["usecase: uc-2"]["status"] == "passed"


def test_a_dry_run_changes_nothing_on_the_remote(tmp_path: Path) -> None:
    work = scratch(tmp_path)
    branch(work, "feat/a", {"a.txt": "a\n"})
    refs = git(tmp_path / "remote.git", "for-each-ref")
    out = intake(work, tmp_path, {"prs": [pr(1, "feat/a")]}, DRY="1")
    assert out["code"] == 0 and "retarget from develop, then merge" in out["stdout"]
    assert git(tmp_path / "remote.git", "for-each-ref") == refs
    assert "PATCH" not in calls(tmp_path) and "cancel" not in calls(tmp_path) and not (tmp_path / "intake").exists()


def test_pull_requests_github_will_not_retarget_are_skipped_and_the_run_stays_green(tmp_path: Path) -> None:
    work = scratch(tmp_path)
    for name in ("done", "queued", "good"):
        branch(work, f"feat/{name}", {f"{name}.txt": f"{name}\n"})
    state = {
        "prs": [
            pr(1, "feat/done"),
            pr(2, "feat/queued"),
            pr(3, "dependabot/npm/x", baseRefName="main"),
            pr(4, "feat/draft", isDraft=True),
            pr(5, "feat/good"),
        ],
        "refuse": {
            "1": "gh: Validation Failed: no new commits between base branch and head branch (HTTP 422)",
            "2": "gh: Pull request has been added to a merge queue (HTTP 422)",
        },
    }
    out = intake(work, tmp_path, state)
    assert out["code"] == 0, out["stderr"]
    assert [m["pr"] for m in out["merged"]] == [5]
    assert {s["pr"]: s["reason"] for s in out["skipped"]} == {
        1: "already in the train",
        2: "queued to develop; merge develop into the train after it lands",
        3: "dependabot is not part of a release",
        4: "draft",
    }
