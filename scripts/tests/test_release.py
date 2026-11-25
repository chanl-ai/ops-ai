"""`make release-pr`, `release-cut`, `hotfix-cut` and `release-version` (scripts/release.py) driven through their
command line on a scratch repository with a fake `gh` and a fake `make`.

Failure modes: a release PR opens on a train whose `make ci-local` is red, that lacks commits of develop, whose
checkout is not its head or whose version file is not the release's; a hotfix PR opens on a head whose CI or staging
deploy with its click walk did not succeed; the body leaves out the merged pull requests or the SDK version; a cut
drops commits of the train that develop does not hold, or does not create a missing train; a hotfix branch is cut from
anywhere but a tag."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "release.py"

FAKE_GH = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
state = json.loads(os.environ["FAKE_GH"])
if args[:2] == ["run", "list"]:
    workflow = args[args.index("--workflow") + 1]
    if workflow not in state["runs"]:
        sys.exit(f"HTTP 404: Not Found (https://api.github.com/repos/o/r/actions/workflows/{workflow})")
    print(json.dumps(state["runs"][workflow]))
elif args[:1] == ["api"] and args[1].endswith("/logs"):
    print(state["log"])
elif args[:2] == ["run", "view"]:
    print(json.dumps({"jobs": state["jobs"][args[2]]}))
elif args[:2] == ["pr", "list"]:
    print(json.dumps([]))
elif args[:2] == ["pr", "create"]:
    with open(os.environ["FAKE_LOG"], "a") as log:
        log.write("gh " + json.dumps(args) + chr(10))
    print("https://github.com/o/r/pull/1")
else:
    sys.exit("fake gh: unexpected " + " ".join(args))
"""

FAKE_MAKE = """#!/bin/sh
echo "make $*" >> "$FAKE_LOG"
exit "${FAKE_MAKE_RC:-0}"
"""

IDENT = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def git(repo: Path, *args: str) -> str:
    env = {**os.environ, **IDENT}
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env).stdout


def release_repo(tmp: Path) -> Path:
    """origin with main and develop at 1.0.0, a tag v1.0.0 on develop, and release/current holding one merged pull
    request that raised the SDK version and the version file to 1.1.0; the checkout is at the train's head."""
    remote, work = tmp / "remote.git", tmp / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "clone", "-q", str(remote), str(work)], check=True, capture_output=True)
    (work / "sdk/python").mkdir(parents=True)
    (work / "sdk/typescript").mkdir(parents=True)
    (work / "sdk/python/pyproject.toml").write_text('[project]\nname = "ops-ai"\nversion = "1.0.0"\n')
    (work / "sdk/typescript/package.json").write_text('{"name": "@chanl-ai/ops-ai", "version": "1.0.0"}\n')
    (work / "deploy/release").mkdir(parents=True)
    (work / "deploy/release/version").write_text("1.0.0\n")
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "first")
    git(work, "push", "-q", "origin", "HEAD:main", "HEAD:develop")
    git(work, "tag", "v1.0.0")
    git(work, "push", "-q", "origin", "v1.0.0")
    git(work, "checkout", "-q", "-b", "feature")
    (work / "sdk/python/pyproject.toml").write_text('[project]\nname = "ops-ai"\nversion = "1.1.0"\n')
    (work / "sdk/typescript/package.json").write_text('{"name": "@chanl-ai/ops-ai", "version": "1.1.0"}\n')
    (work / "deploy/release/version").write_text("1.1.0\n")
    git(work, "commit", "-q", "-am", "feat(sdk): add runs.cancel")
    git(work, "checkout", "-q", "-b", "release/current", "v1.0.0")
    git(work, "merge", "-q", "--no-ff", "feature", "-m", "Merge pull request #12 from chanl-ai/feat/sdk-runs-cancel")
    git(
        work,
        "commit",
        "-q",
        "--amend",
        "-m",
        "Merge pull request #12 from chanl-ai/feat/sdk-runs-cancel",
        "-m",
        "feat(sdk): add runs.cancel",
    )
    git(work, "push", "-q", "origin", "release/current")
    git(work, "fetch", "-q", "origin")
    return work


def release_pr(
    work: Path, tmp: Path, gh_state: dict[str, Any] | None = None, command: str = "pr", **env_changes: str
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name, text in (("gh", FAKE_GH), ("make", FAKE_MAKE)):
        (bin_dir / name).write_text(text)
        (bin_dir / name).chmod(0o755)
    env = {
        **os.environ,
        **IDENT,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "V": "1.1.0",
        "FAKE_GH": json.dumps(gh_state or {}),
        "FAKE_LOG": str(tmp / "calls.log"),
    }
    env.update(env_changes)
    return subprocess.run(
        [sys.executable, str(SCRIPT), command], cwd=work, capture_output=True, text=True, env=env, check=False
    )


def calls(tmp: Path) -> str:
    log = tmp / "calls.log"
    return log.read_text() if log.exists() else ""


def advance(work: Path, branch: str, name: str) -> str:
    """One more commit on origin's `branch`, made from a throwaway branch so the checkout stays where it is."""
    git(work, "checkout", "-q", "-b", "tmp-advance", f"origin/{branch}")
    (work / name).write_text(name)
    git(work, "add", name)
    git(work, "commit", "-q", "-m", name)
    git(work, "push", "-q", "origin", f"HEAD:{branch}")
    git(work, "checkout", "-q", "release/current")
    git(work, "branch", "-q", "-D", "tmp-advance")
    git(work, "fetch", "-q", "origin")
    return git(work, "rev-parse", f"origin/{branch}").strip()


def test_the_train_pr_runs_ci_local_and_opens_into_develop_with_the_release_title(tmp_path: Path) -> None:
    work = release_repo(tmp_path)
    dry = release_pr(work, tmp_path)
    assert dry.returncode == 0, dry.stderr
    assert "release: 1.1.0 into develop" in dry.stdout and "dry run" in dry.stdout
    assert "ci-local" not in calls(tmp_path)
    run = release_pr(work, tmp_path, DRY="0")
    assert run.returncode == 0, run.stderr
    assert "make -C" in calls(tmp_path) and "ci-local BASE=origin/develop" in calls(tmp_path)
    create = next(line for line in calls(tmp_path).splitlines() if line.startswith("gh "))
    args = json.loads(create[3:])
    assert args[args.index("--base") + 1] == "develop" and args[args.index("--head") + 1] == "release/current"
    assert args[args.index("--title") + 1] == "release: 1.1.0 into develop"
    body = args[args.index("--body") + 1]
    assert "#12 feat(sdk): add runs.cancel" in body and "sdk/**: changed" in body
    assert "python ops-ai 1.0.0 -> 1.1.0" in body and "typescript @chanl-ai/ops-ai 1.0.0 -> 1.1.0" in body
    assert "make ci-local green" in body and "no pull request to main" in body


def test_it_refuses_a_red_ci_local_and_opens_nothing(tmp_path: Path) -> None:
    run = release_pr(release_repo(tmp_path), tmp_path, DRY="0", FAKE_MAKE_RC="1")
    assert run.returncode == 1 and "ci-local is red" in run.stderr
    assert "gh " not in calls(tmp_path)


def test_it_refuses_a_train_that_lacks_develop_a_checkout_off_the_head_or_a_dirty_one(tmp_path: Path) -> None:
    work = release_repo(tmp_path)
    advance(work, "develop", "hotfix-landed")
    behind = release_pr(work, tmp_path, DRY="0")
    assert behind.returncode == 1 and "lacks commits of origin/develop" in behind.stderr
    git(work, "merge", "-q", "--no-ff", "origin/develop", "-m", "chore: merge develop")
    git(work, "push", "-q", "origin", "release/current")
    (work / "dirty").write_text("x")
    git(work, "add", "dirty")
    dirty = release_pr(work, tmp_path, DRY="0")
    assert dirty.returncode == 1 and "uncommitted" in dirty.stderr
    git(work, "reset", "-q", "--hard", "HEAD~1")
    stale = release_pr(work, tmp_path, DRY="0")
    assert stale.returncode == 1 and "not at origin/release/current" in stale.stderr
    assert "ci-local" not in calls(tmp_path)


def test_a_version_file_that_is_not_the_release_blocks_the_pr_and_set_version_fixes_it(tmp_path: Path) -> None:
    work = release_repo(tmp_path)
    wrong = release_pr(work, tmp_path, V="1.2.0")
    assert wrong.returncode == 1 and "says 1.1.0, not 1.2.0" in wrong.stderr
    done = release_pr(work, tmp_path, command="set-version", V="1.2.0", DRY="0")
    assert done.returncode == 0, done.stderr
    git(work, "fetch", "-q", "origin")
    assert git(work, "show", "origin/release/current:deploy/release/version") == "1.2.0\n"
    again = release_pr(work, tmp_path, command="set-version", V="1.2.0", DRY="0")
    assert "already says 1.2.0" in again.stdout


def test_the_cut_fast_forwards_the_train_to_develop_after_a_release_and_never_drops_its_commits(tmp_path: Path) -> None:
    work = release_repo(tmp_path)
    dropped = release_pr(work, tmp_path, command="cut", DRY="0")
    assert dropped.returncode == 1 and "holds commits origin/develop lacks" in dropped.stderr
    git(work, "push", "-q", "origin", "release/current:develop")
    develop = advance(work, "develop", "after-release")
    done = release_pr(work, tmp_path, command="cut", DRY="0")
    assert done.returncode == 0, done.stderr
    git(work, "fetch", "-q", "origin")
    assert git(work, "rev-parse", "origin/release/current").strip() == develop


def test_the_cut_creates_a_missing_train_at_develop(tmp_path: Path) -> None:
    work = release_repo(tmp_path)
    git(work, "push", "-q", "origin", "--delete", "release/current")
    assert "is missing" in release_pr(work, tmp_path, command="cut").stdout
    done = release_pr(work, tmp_path, command="cut", DRY="0")
    assert done.returncode == 0, done.stderr
    git(work, "fetch", "-q", "origin")
    assert git(work, "rev-parse", "origin/release/current").strip() == git(work, "rev-parse", "origin/develop").strip()


def test_a_hotfix_is_cut_from_the_tag_with_the_version_set_and_needs_a_name(tmp_path: Path) -> None:
    work = release_repo(tmp_path)
    advance(work, "develop", "unreleased")
    assert release_pr(work, tmp_path, command="hotfix-cut", V="1.0.1", DRY="0").returncode == 1
    run = release_pr(work, tmp_path, command="hotfix-cut", V="1.0.1", HOTFIX="login-loop", DRY="0")
    assert run.returncode == 0, run.stderr
    git(work, "fetch", "-q", "origin")
    assert git(work, "show", "origin/hotfix/login-loop:deploy/release/version") == "1.0.1\n"
    assert git(work, "rev-parse", "origin/hotfix/login-loop^").strip() == git(work, "rev-parse", "v1.0.0").strip()


STAGING_JOB = {"name": "staging / deploy", "conclusion": "success", "databaseId": 11}
READY: dict[str, Any] = {
    "runs": {"ci.yml": [{"databaseId": 1, "conclusion": "success", "status": "completed"}]},
    "jobs": {"1": [STAGING_JOB]},
    "log": "stg-deploy: click walk (41 OK, 0 FAIL)",
}


def ready(**changes: Any) -> dict[str, Any]:
    return {**READY, **changes}


def hotfix_branch(work: Path) -> None:
    advance(work, "develop", "unreleased")
    done = release_pr(work, work.parent, command="hotfix-cut", V="1.0.1", HOTFIX="login-loop", DRY="0")
    assert done.returncode == 0, done.stderr
    git(work, "fetch", "-q", "origin")
    advance(work, "hotfix/login-loop", "the-fix")


@pytest.mark.parametrize(
    ("state", "named"),
    [
        (
            ready(
                runs={**READY["runs"], "ci.yml": [{"databaseId": 1, "conclusion": "failure", "status": "completed"}]}
            ),
            "ci.yml",
        ),
        (ready(jobs={"1": []}), "no staging deploy"),
        (ready(jobs={"1": [{**STAGING_JOB, "conclusion": "failure"}]}), "failure"),
        (ready(log="stg-deploy: click walk skipped (SKIP_WALK=1)"), "click walk"),
        (ready(log="stg-deploy: click walk (40 OK, 1 FAIL)"), "1 FAIL"),
    ],
)
def test_a_hotfix_pr_is_refused_unless_ci_and_the_staging_deploy_with_its_walk_succeeded(
    tmp_path: Path, state: dict[str, Any], named: str
) -> None:
    work = release_repo(tmp_path)
    hotfix_branch(work)
    run = release_pr(work, tmp_path, state, V="1.0.1", HOTFIX="login-loop")
    assert run.returncode == 1
    assert named in run.stderr
    assert "hotfix: 1.0.1" not in run.stdout


def test_a_hotfix_pr_is_titled_for_develop_and_lists_only_the_fix(tmp_path: Path) -> None:
    work = release_repo(tmp_path)
    hotfix_branch(work)
    run = release_pr(work, tmp_path, READY, V="1.0.1", HOTFIX="login-loop")
    assert run.returncode == 0, run.stderr
    assert "hotfix: 1.0.1 into develop" in run.stdout and "the-fix" in run.stdout
    assert "unreleased" not in run.stdout and "sdk/**: unchanged" in run.stdout
